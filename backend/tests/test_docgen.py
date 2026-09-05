import os
import hashlib
import shutil
from pathlib import Path
import pytest
from docx import Document

from app.tools.docgen import docgen
from app.contracts import DocgenArgs, ErrorCode
from app.tools.base import ToolContext, ToolError

@pytest.fixture
def docx_template(tmp_path):
    doc = Document()
    doc.add_paragraph('Title: {{TITLE}}')
    doc.add_paragraph('Summary:\n{{EXEC_SUMMARY}}')
    
    table = doc.add_table(rows=1, cols=2)
    cell = table.cell(0, 0)
    cell.text = "Findings:"
    cell = table.cell(0, 1)
    cell.text = "{{FINDINGS_LIST}}"
    
    section = doc.sections[0]
    header = section.header
    header.paragraphs[0].text = "Header: {{HEADER_MARKER}}"
    
    tpl_path = tmp_path / "test_template.docx"
    doc.save(str(tpl_path))
    return tpl_path

@pytest.fixture
def mock_ctx(tmp_path):
    class MockCtx(ToolContext):
        def __init__(self):
            self.mock = False
            self._root = tmp_path
        
        def resolve(self, path: str) -> Path:
            return self._root / path
            
        def new_artifact_name(self, name: str) -> str:
            return "test_generated_" + name
            
        def register_artifact(self, path: Path, media_type: str, simulated: bool):
            class Ref:
                artifact_id = "test_art_id"
                def __init__(self, root, p):
                    self.path = str(p.relative_to(root))
                    self.size_bytes = p.stat().st_size
                    with open(p, "rb") as f:
                        self.sha256 = hashlib.sha256(f.read()).hexdigest()
            return Ref(self._root, path)
            
    return MockCtx()

def test_docgen_docx_full(docx_template, mock_ctx):
    # F. Template integrity - calculate original hash
    with open(docx_template, "rb") as f:
        orig_hash = hashlib.sha256(f.read()).hexdigest()
        
    data = {
        "TITLE": "Test Approval Note",
        "EXEC_SUMMARY": "This is a multiline\nsummary of the inspection.",
        "FINDINGS_LIST": [
            {"text": "Finding 1"},
            "Finding 2"
        ],
        "HEADER_MARKER": "Confidential"
    }
    
    args = DocgenArgs(
        kind="docx",
        data=data,
        template=str(docx_template.name),
        out_name="out.docx"
    )
    
    # Run tool
    res = docgen(args, mock_ctx)
    
    # G. Return contract
    assert res["kind"] == "docx"
    assert res["artifact_id"] == "test_art_id"
    assert "path" in res
    assert res["size_bytes"] > 0
    assert "sha256" in res
    
    # A. Basic generation
    out_path = mock_ctx._root / res["path"]
    assert out_path.exists()
    
    # F. Template integrity check again
    with open(mock_ctx._root / docx_template.name, "rb") as f:
        new_hash = hashlib.sha256(f.read()).hexdigest()
    assert orig_hash == new_hash, "Template was modified!"
    
    # Parse generated doc
    doc = Document(str(out_path))
    
    text = ""
    for p in doc.paragraphs:
        text += p.text + "\n"
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    text += p.text + "\n"
    for section in doc.sections:
        for p in section.header.paragraphs:
            text += p.text + "\n"
            
    # B. Marker replacement
    assert "{{TITLE}}" not in text
    assert "{{EXEC_SUMMARY}}" not in text
    assert "{{FINDINGS_LIST}}" not in text
    assert "{{HEADER_MARKER}}" not in text
    
    # C. Content correctness
    assert "Test Approval Note" in text
    assert "Confidential" in text
    
    # D. Tables
    assert "Finding 1" in text
    assert "Finding 2" in text
    
    # E. Multiline content
    assert "This is a multiline\nsummary" in text

def test_docgen_invalid_input(mock_ctx):
    # H. Invalid input
    args = DocgenArgs(
        kind="docx",
        data={},
        template="does_not_exist.docx",
        out_name="out.docx"
    )
    with pytest.raises(ToolError) as excinfo:
        docgen(args, mock_ctx)
    assert excinfo.value.code == ErrorCode.NOT_FOUND
