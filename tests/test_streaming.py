import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lab_model_monitor.streaming import read_responses
from lab_model_monitor.monitor import run_monitor
from lab_model_monitor.store import RunStore
from lab_model_monitor.schedule import AIReasoningSchedule
from lab_model_monitor.client import OpenAICompatibleClient, GPTClientConfig

def event(kind, **kwargs):
    return ('data: ' + json.dumps({'type': kind, **kwargs}) + '\n\n').encode()

class StreamingTests(unittest.TestCase):
    def test_default_responses_client_reads_incrementally(self):
        class Incoming(io.BytesIO):
            headers = {'Content-Type': 'text/event-stream; charset=utf-8'}
            def read(self, *args):
                raise AssertionError('Whole response read is forbidden')
        incoming=Incoming(event('response.output_text.delta',delta='21') +
                          event('response.completed',response={'status':'completed','id':'r1','usage':{'total_tokens':7}}))
        client=OpenAICompatibleClient(api_key='fake',config=GPTClientConfig('https://example.test/v1','m1'),retry_stream_failures=False)
        updates=[]
        with patch('urllib.request.urlopen',return_value=incoming) as transport:
            response=client.generate_text(instructions='solve',input_text='candy',on_progress=updates.append)
        self.assertTrue(json.loads(transport.call_args.args[0].data)['stream'])
        self.assertEqual(response.text,'21')
        self.assertEqual(response.total_tokens,7)
        self.assertEqual(updates[0]['response_text'],'21')

    def test_terminal_does_not_wait_for_connection_close(self):
        class Stream(io.BytesIO):
            def readline(self, *args):
                result = super().readline(*args)
                if not result:
                    raise AssertionError('Read beyond terminal event')
                return result
        progress = []
        result = read_responses(Stream(event('response.output_text.delta', delta='绵羊') +
            event('response.completed', response={'id': 'r1','status':'completed','usage':{'total_tokens':5}})), progress.append)
        self.assertEqual(result['output_text'], '绵羊')
        self.assertEqual(result['usage']['total_tokens'], 5)
        self.assertEqual(progress[0]['received_characters'], 2)

    def test_unfinished_stream_is_not_completed(self):
        result = read_responses(io.BytesIO(event('response.output_text.delta', delta='<html>')))
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['output_text'], '<html>')

    def test_partial_saved_before_network_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = RunStore(root/'db')
            settings={'api':{'base_url':'https://example.test/v1','api_mode':'responses'},
                      'schedule':AIReasoningSchedule(attempts_per_model=1,models=('m1',)).to_dict()}
            def generate(_client, **kwargs):
                kwargs['on_progress']({'response_text':'<html>partial','stream_event_count':2})
                saved=store.recent()[0]['samples'][0]
                self.assertEqual(saved['response_text'],'<html>partial')
                self.assertEqual(saved['status'],'running')
                raise TimeoutError()
            with patch.object(OpenAICompatibleClient,'generate_text',generate):
                result=run_monitor(settings=settings,credentials={'api_key':'fake'},store=store,
                                   lock_path=root/'lock',animation_test=True)
            sample=store.get(result['run_id'])['samples'][0]
            self.assertEqual(sample['status'],'timeout')
            self.assertEqual(sample['response_text'],'<html>partial')
