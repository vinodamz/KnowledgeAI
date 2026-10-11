import asyncio
import logging
from types import SimpleNamespace
import httpx
import pytest
from knowledge_ai.ingestion.gemini import GeminiProvider,ProviderFailure

class Stream(httpx.AsyncByteStream):
    def __init__(self,slow=False):self.slow=slow;self.reads=0;self.closed=False
    async def __aiter__(self):
        for _ in range(100):
            self.reads+=1
            if self.slow:await asyncio.sleep(.02)
            yield b'x'*8192
    async def aclose(self):self.closed=True

def provider(stream,deadline=1):
    transport=httpx.MockTransport(lambda request:httpx.Response(200,stream=stream))
    return GeminiProvider(SimpleNamespace(gemini_api_key='private-key',gemini_model='test'),transport=transport,deadline=deadline)

def test_oversized_provider_body_stops_stream_early():
    stream=Stream()
    with pytest.raises(ProviderFailure,match='limit'):provider(stream).extract([],{'entities':[]})
    assert stream.reads<100 and stream.closed

def test_provider_overall_deadline_closes_slow_stream():
    stream=Stream(slow=True)
    with pytest.raises(ProviderFailure,match='deadline'):provider(stream,deadline=.005).extract([],{'entities':[]})
    assert stream.reads<100 and stream.closed

@pytest.mark.parametrize("registry",[True,False])
def test_registry_failure_diagnostic_contains_no_exception_content(caplog,monkeypatch,registry):
    import knowledge_ai.worker as worker
    from sqlalchemy.exc import SQLAlchemyError
    error_type=SQLAlchemyError if registry else RuntimeError
    def fail(*args):raise error_type('private-key raw source provider body')
    monkeypatch.setattr(worker,'run_one',fail)
    with caplog.at_level(logging.ERROR):assert not worker.poll_once(object(),object())
    assert ('registry_failure' if registry else 'worker_failure') in caplog.text
    assert 'private-key' not in caplog.text and 'raw source' not in caplog.text
