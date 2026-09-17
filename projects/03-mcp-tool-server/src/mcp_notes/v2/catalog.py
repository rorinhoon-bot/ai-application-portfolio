"""Bounded immutable snapshot, loaded through existing Windows HANDLE safety."""
import hashlib
import json
from types import MappingProxyType

from mcp_notes import safe_open
from mcp_notes.index import build_index
from mcp_notes.search import _make_excerpt, _normalize
from .contracts import Document, Hit, ToolFailure


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


class Catalog:
    def __init__(self, documents):
        docs = {d.note_id: d for d in documents}
        if len(docs) != len(documents) or len(docs) > 64:
            raise ToolFailure("snapshot-invalid")
        if sum(len(d.text.encode("utf-8")) for d in documents) > 262144:
            raise ToolFailure("content-too-large")
        self.documents = MappingProxyType(docs)
        self.snapshot_hash = digest([docs[k].model_dump() for k in sorted(docs)])

    @classmethod
    def load(cls, root):
        try:
            entries = build_index(str(root))
            if len(entries) > 64 or any(e.size > 8192 for e in entries):
                raise ToolFailure("content-too-large")
            if sum(e.size for e in entries) > 262144:
                raise ToolFailure("content-too-large")
            documents = []
            handle = safe_open._nt_open(0, safe_open.configure_root(str(root)), is_dir=True)
            try:
                for entry in entries:
                    data = safe_open.open_file_relative(handle, entry.relative_path.split("/"))
                    if len(data) != entry.size or hashlib.sha256(data).hexdigest() != entry.sha256:
                        raise ToolFailure("snapshot-invalid")
                    documents.append(Document(note_id=entry.note_id, title=entry.title,
                                              text=data.decode("utf-8"), content_sha256=entry.sha256))
            finally:
                safe_open._close(handle)
            return cls(documents)
        except ToolFailure:
            raise
        except (UnicodeError, ValueError):
            raise ToolFailure("snapshot-invalid") from None
        except Exception:
            raise ToolFailure("index-build-failed") from None

    def search(self, keyword):
        keyword = _normalize(keyword)
        hits = []
        for note_id in sorted(self.documents):
            document = self.documents[note_id]
            text = _normalize(document.text)
            count = text.count(keyword)
            if count:
                hits.append(Hit(note_id=note_id, title=document.title,
                                excerpt=_make_excerpt(text, keyword), match_count=count,
                                content_sha256=document.content_sha256))
        return hits[:5], len(hits)

    def read(self, note_id):
        if note_id not in self.documents:
            raise ToolFailure("not-registered")
        return self.documents[note_id]
