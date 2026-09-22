"""Bounded tokenization using P1's actual sparse tokenizer; no retrieval service."""
import json
import sys


def offline(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo', 'socket.bind'):
        raise RuntimeError('OFFLINE_NETWORK_BLOCKED')


sys.addaudithook(offline)
from cited_rag.sparse import tokenize_sparse


def handle(payload):
    if set(payload) != {'texts'} or type(payload['texts']) is not list or not 1 <= len(payload['texts']) <= 70:
        raise ValueError('TOKEN_INPUT_INVALID')
    texts = payload['texts']
    if any(type(t) is not str or len(t.encode()) > 8192 for t in texts):
        raise ValueError('TOKEN_INPUT_INVALID')
    if sum(len(t.encode()) for t in texts) > 102400:
        raise ValueError('TOKEN_INPUT_INVALID')
    # Unique tokens bound the response; ranking deliberately uses set overlap, not BM25.
    return {'tokens': [sorted(set(tokenize_sparse(t))) for t in texts]}


if __name__ == '__main__':
    raw = sys.stdin.buffer.read(393217)
    if len(raw) > 393216:
        raise ValueError('TOKEN_INPUT_INVALID')
    print(json.dumps(handle(json.loads(raw)), ensure_ascii=False))
