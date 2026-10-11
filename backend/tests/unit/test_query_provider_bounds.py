import asyncio
import httpx
import pytest
from fastapi import HTTPException
from knowledge_ai.adapters.lightrag import QueryEmbeddingProvider

class Stream(httpx.AsyncByteStream):
    def __init__(self,slow=False):self.slow=slow;self.reads=0;self.closed=False
    async def __aiter__(self):
        for _ in range(100):
            self.reads+=1
            if self.slow:await asyncio.sleep(.02)
            yield b'x'*8192
    async def aclose(self):self.closed=True

@pytest.mark.parametrize('slow',[False,True])
def test_embedding_stream_bytes_and_deadline_bounded(settings,slow):
    stream=Stream(slow)
    transport=httpx.MockTransport(lambda request:httpx.Response(200,stream=stream))
    with pytest.raises(HTTPException) as error:
        QueryEmbeddingProvider(settings,transport=transport,deadline=.005 if slow else 1).embed('query')
    assert error.value.status_code==503 and stream.closed and stream.reads<100
    assert 'x' * 20 not in str(error.value.detail)
