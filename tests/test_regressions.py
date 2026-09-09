"""SDK·외부 API를 호출하지 않는 회귀 검증. 실제 runs는 변경하지 않는다."""
import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app import agent, compliance, server, store, tools


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(store, 'RUNS', Path(self.temp.name))
        self.patch.start()
        store.create_run('test', {'name': '테스트'}, 'b2c-goods')
        server._contexts.clear()

    def tearDown(self):
        server._contexts.clear()
        self.patch.stop()
        self.temp.cleanup()

    def post(self, action, body):
        h = object.__new__(server.Handler)
        h.path = '/api/run/test/' + action
        h._body = lambda: body
        h._json = lambda obj, code=200: (code, obj)
        return h.do_POST()

    def question(self):
        q = {'question_id': 'q1', 'version': 1, 'question': '선택'}
        store.update('test', status='waiting_for_user', pending_question=q)
        return dict(question_id='q1', version=1, answer=['A'])

    def complete_files(self):
        base = store.artifacts_dir('test')
        blocks = compliance.load_rules()['required_blocks']['all']
        html = ' '.join(b['any_of'][0] for b in blocks)
        for name, text in {'detail-page.html': html, 'storyboard.md': '구성', 'plan.md': '기획',
                           'image-prompts.json': '[]', 'listing.json': json.dumps({
                               'product_name': '요가 매트', 'tags': [str(i) for i in range(10)],
                               'category': '요가매트', 'notice': {'품명': '요가매트'}})}.items():
            (base / name).write_text(text)

    def run_mock(self, error=False, no_result=False):
        async def fake_query(**kwargs):
            if not no_result:
                yield type('ResultMessage', (), {'is_error': error, 'result': '테스트 엔진 오류',
                                                'total_cost_usd': 0.1, 'usage': {}})()
        with patch.object(agent, 'query', fake_query):
            asyncio.run(agent.run_agent('test', tools.RunContext('test', 'b2c-goods')))

    def test_engine_error_never_done(self):
        self.complete_files(); self.run_mock(error=True)
        self.assertEqual(store.load('test')['status'], 'failed')

    def test_missing_result_never_done(self):
        self.complete_files(); self.run_mock(no_result=True)
        self.assertEqual(store.load('test')['status'], 'halted')

    def test_missing_artifacts_never_done(self):
        self.run_mock()
        self.assertIn('산출물 누락', store.load('test')['halt_reason'])

    def test_final_gate_requires_explicit_user_answer(self):
        self.complete_files(); self.run_mock()
        s = store.load('test')
        self.assertEqual(s['status'], 'waiting_for_user')
        q = s['pending_question']
        answer = dict(question_id=q['question_id'], version=1, answer=['최종 승인'])
        code, _ = self.post('answer', answer)
        self.assertEqual(code, 200)
        self.assertEqual(store.load('test')['status'], 'done')
        self.assertTrue(self.post('answer', answer)[1]['duplicate'])

    def test_final_gate_rechecks_changed_file(self):
        self.complete_files(); self.run_mock()
        q = store.load('test')['pending_question']
        (store.artifacts_dir('test') / 'detail-page.html').write_text('치료')
        self.assertEqual(self.post('answer', dict(question_id=q['question_id'], version=1,
                                                answer=['최종 승인']))[0], 409)

    def test_duplicate_answer_live(self):
        body = self.question(); c = tools.RunContext('test', 'b2c-goods')
        server._contexts['test'] = c
        self.assertEqual(self.post('answer', body)[0], 200)
        self.assertTrue(c.answer_event.is_set())
        self.assertTrue(self.post('answer', body)[1]['duplicate'])
        self.assertEqual(len(store.load('test')['answers']), 1)
        self.assertEqual(self.post('answer', {**body, 'answer': ['B']})[0], 409)

    def test_duplicate_answer_after_restart(self):
        body = self.question()
        with patch.object(server, 'start_run') as start:
            self.post('answer', body); self.post('answer', body)
            self.assertEqual(start.call_count, 1)

    def test_stale_answer_does_not_replace_question(self):
        body = self.question()
        self.assertEqual(self.post('answer', {**body, 'question_id': 'old'})[0], 409)
        self.assertIsNotNone(store.load('test')['pending_question'])

    def test_resume_cannot_skip_gate_or_duplicate_worker(self):
        self.question()
        self.assertEqual(self.post('resume', {})[0], 409)
        store.update('test', pending_question=None)
        server._contexts['test'] = tools.RunContext('test', 'b2c-goods')
        self.assertEqual(self.post('resume', {})[0], 409)

    def test_worker_context_removed(self):
        finished = threading.Event()
        with patch.object(agent, 'run_in_thread', lambda *a: finished.set()):
            self.assertTrue(server.start_run('test'))
            finished.wait(1)
            # Acquire after worker finally has had an opportunity; join created daemon.
            for t in threading.enumerate():
                if t.name.endswith('(worker)'):
                    t.join(1)
            self.assertNotIn('test', server._contexts)

    def test_cancel_wakes_human_wait(self):
        c = tools.RunContext('test', 'b2c-goods'); server._contexts['test'] = c
        self.post('cancel', {})
        self.assertTrue(c.cancelled and c.answer_event.is_set() and c.approval_event.is_set())

    def test_path_escape_and_symlink_rejected(self):
        c = tools.RunContext('test', 'b2c-goods'); tools.set_context(c)
        base = store.artifacts_dir('test'); (base/'link').symlink_to(base/'target')
        for path in ['../escape', '/tmp/escape', 'link']:
            r = asyncio.run(tools.save_artifact.handler({'path': path, 'content': 'x'}))
            self.assertIn('error', json.loads(r['content'][0]['text']))

    def test_medical_word_and_missing_blocks(self):
        self.assertGreater(compliance.check('비염 치료', 'regulated')['block_count'], 0)
        self.assertFalse(compliance.check('요가매트', 'b2b-inquiry', 'full_page')['passed'])

    def test_valid_artifact_write(self):
        tools.set_context(tools.RunContext('test', 'b2c-goods'))
        r = asyncio.run(tools.save_artifact.handler({'path': 'nested/plan.md', 'content': '기획'}))
        self.assertTrue(json.loads(r['content'][0]['text'])['ok'])
        self.assertEqual((store.artifacts_dir('test') / 'nested/plan.md').read_text(), '기획')

    def test_three_tool_failures_halt(self):
        tools.set_context(tools.RunContext('test', 'b2c-goods'))
        for _ in range(3):
            asyncio.run(tools.read_playbook.handler({'section': 'unknown'}))
        self.assertEqual(store.load('test')['halt_reason'], '도구 연속 실패 3회')

    def test_init_session_saved_before_result(self):
        async def fake_query(**kwargs):
            yield type('SystemMessage', (), {'data': {'session_id': 'test-session'}})()
            raise RuntimeError('연결 중단')
        with patch.object(agent, 'query', fake_query):
            asyncio.run(agent.run_agent('test', tools.RunContext('test', 'b2c-goods')))
        self.assertEqual(store.load('test')['session_id'], 'test-session')
        self.assertFalse(store.load('test')['usage']['cost_complete'])

    def test_human_wait_excluded_from_time_budget(self):
        c = tools.RunContext('test', 'b2c-goods', waiting_s=1900)
        async def fake_query(**kwargs):
            yield type('ResultMessage', (), {'is_error': False, 'total_cost_usd': 0.1, 'usage': {}})()
        self.complete_files()
        with patch.object(agent, 'query', fake_query), patch.object(agent.time, 'time', side_effect=[0]+[2000]*30):
            asyncio.run(agent.run_agent('test', c))
        s = store.load('test')
        self.assertEqual(s['status'], 'waiting_for_user')
        self.assertEqual(s['usage']['working_s'], 100)

    def test_dead_image_approval_can_be_rejected(self):
        store.update('test', pending_approval={'tool': 'generate_image'})
        self.assertEqual(self.post('approve', {'approved': True})[0], 409)
        self.assertEqual(self.post('approve', {'approved': False})[0], 200)
        self.assertIsNone(store.load('test')['pending_approval'])


if __name__ == '__main__':
    unittest.main()
