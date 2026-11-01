# 퀴즈 생성의 사용자 AI 키 처리 테스트 (DB·AI 호출 없이 mock). 실행: python -m unittest tests.test_quiz_user_key
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_user, get_db
from app.error_handlers import register_exception_handlers
from app.routers import quiz as quiz_router
from app.services import claude_service

BODY = {"document_id": 1, "quiz_type": "객관식"}


def make_client(db):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(quiz_router.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, raise_server_exceptions=False)


class QuizUserKeyTest(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.get.return_value = SimpleNamespace(id=1, user_id=7)
        self.client = make_client(self.db)

    def post(self, headers=None):
        return self.client.post("/api/quiz/generate", json=BODY, headers=headers or {})

    def test_no_key_returns_400_ai_key_required(self):
        with patch.object(claude_service.settings, "allow_server_ai_key", False):
            r = self.post()
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error_code"], "AI_KEY_REQUIRED")
        self.db.add.assert_not_called()

    def test_invalid_provider(self):
        r = self.post({"X-AI-Provider": "gemini", "X-AI-Key": "sk-secret"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error_code"], "AI_PROVIDER_INVALID")
        self.assertNotIn("sk-secret", r.text)

    def test_user_key_is_passed_and_set_saved(self):
        qs = [{"question": "Q", "options": ["a", "b", "c", "d"], "correct_answer": "a", "explanation": ""}]
        with patch.object(quiz_router, "generate_quiz_questions", return_value=qs) as gen:
            self.post({"X-AI-Provider": "OpenAI", "X-AI-Key": "sk-secret"})
        self.assertEqual((gen.call_args.kwargs["provider"], gen.call_args.kwargs["api_key"]), ("openai", "sk-secret"))

    def test_server_key_fallback_when_allowed(self):
        with patch.object(claude_service.settings, "allow_server_ai_key", True), \
             patch.object(quiz_router, "generate_quiz_questions", return_value=[]) as gen:
            self.post()
        self.assertEqual((gen.call_args.kwargs["provider"], gen.call_args.kwargs["api_key"]), (None, None))

    def test_ai_failure_leaves_nothing_in_db_and_hides_key(self):
        err = claude_service.AIProviderError(400, "AI_KEY_INVALID", "API 키를 확인해주세요.")
        with patch.object(quiz_router, "generate_quiz_questions", side_effect=err):
            r = self.post({"X-AI-Provider": "claude", "X-AI-Key": "sk-secret"})
        self.assertEqual((r.status_code, r.json()["error_code"]), (400, "AI_KEY_INVALID"))
        self.assertNotIn("sk-secret", r.text)
        self.db.add.assert_not_called()
        self.db.commit.assert_not_called()

    def test_save_error_rolls_back(self):
        self.db.flush.side_effect = RuntimeError("boom")
        with patch.object(quiz_router, "generate_quiz_questions", return_value=[{"question": "Q"}]):
            r = self.post({"X-AI-Provider": "claude", "X-AI-Key": "sk-secret"})
        self.assertEqual(r.status_code, 500)
        self.db.rollback.assert_called()
        self.db.commit.assert_not_called()


class CompleteUserKeyTest(unittest.TestCase):
    def test_provider_error_is_translated_without_key(self):
        import anthropic, httpx
        req = httpx.Request("POST", "https://api.anthropic.com")
        exc = anthropic.AuthenticationError("bad key sk-secret", response=httpx.Response(401, request=req), body=None)
        with patch.object(claude_service.anthropic, "Anthropic") as cls:
            cls.return_value.messages.create.side_effect = exc
            with self.assertRaises(claude_service.AIProviderError) as ctx:
                claude_service.complete("sys", "msg", provider="claude", api_key="sk-secret")
        self.assertEqual(ctx.exception.error_code, "AI_KEY_INVALID")
        self.assertNotIn("sk-secret", str(ctx.exception))
        self.assertEqual(cls.call_args.kwargs["max_retries"], 0)


if __name__ == "__main__":
    unittest.main()
