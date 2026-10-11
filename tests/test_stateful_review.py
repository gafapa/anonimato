"""Generated action sequences compared with an independent review model."""
import copy
import tempfile
from unittest.mock import Mock
import pytest
from hypothesis import settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule
from app.api import Api, Doc
from app.engine import pipeline, verify
from app.engine.types import Options
from app.engine.worker import EngineError
from tests.test_security import NoEngine, pdf_with_text


class ReviewSequences(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.folder = tempfile.TemporaryDirectory(prefix='anonimato-stateful-')
        self.api = Api(engine=NoEngine(), light=NoEngine())
        self.options = Options(categories={'manual'}, ocr=False, ai=False, faces=False, signatures=False,
                               handwriting=False, llm_review=False)
        data = pdf_with_text('FICTITIOUS SEQUENCE FIXTURE')
        self.doc = Doc('d1', 'fictitious.pdf', len(data), data, status='ready',
                       analysis=pipeline.analyze(data, 'fictitious.pdf', self.options))
        self.api._state.docs['d1'] = self.doc
        self.api._state.order = ['d1']
        self.model, self.undo, self.redo = [], [], []
        self.revision, self.saved = 0, None

    def record(self):
        self.undo.append(copy.deepcopy(self.model))
        self.redo.clear()
        self.undo = self.undo[-40:]
        self.revision += 1

    @rule(x=st.integers(0, 80), y=st.integers(0, 80))
    def add(self, x, y):
        self.record()
        rect = [x / 100, y / 100, (x + 10) / 100, (y + 10) / 100]
        item = self.api.add_manual('d1', 0, rect)
        self.model.append({'token': item['token'], 'enabled': True, 'rect': rect})

    @rule(enabled=st.booleans())
    def toggle(self, enabled):
        if not self.model:
            return
        if self.model[0]['enabled'] != enabled:
            self.record()
            self.model[0]['enabled'] = enabled
        self.api.set_enabled('d1', [self.doc.analysis.findings[0].id], enabled)

    @rule()
    def remove(self):
        if self.model:
            self.record()
            self.api.remove_manual('d1', self.doc.analysis.findings[0].id)
            self.model.pop(0)

    @rule(redo=st.booleans())
    def restore(self, redo):
        source, destination = (self.redo, self.undo) if redo else (self.undo, self.redo)
        if source:
            destination.append(copy.deepcopy(self.model))
            self.model = source.pop()
            self.revision += 1
        self.api.restore_review('d1', redo)

    @rule(outcome=st.sampled_from(['success', 'cancel', 'error']))
    def reanalyze(self, outcome):
        if outcome == 'success':
            self.api._engine.call = Mock(return_value=pipeline.analyze(self.doc.data, self.doc.name, self.options))
            self.revision += 1
            self.undo.clear()
            self.redo.clear()
        else:
            error = pipeline.Cancelled() if outcome == 'cancel' else EngineError('fictitious failure')
            self.api._engine.call = Mock(side_effect=error)
        self.api._run(['d1'], self.options)

    @rule()
    def save(self):
        self.api._engine.call = Mock(return_value=pipeline.ExportResult(self.doc.data, verify.Report(),
                                                                        'documento-1_anonimizado.pdf', 0))
        result = self.api.export_folder(self.folder.name, {})
        assert result['saved'] == 1 and result['ok']
        self.saved = self.revision

    @rule()
    def rejected_busy_edit(self):
        self.api._state.busy = True
        try:
            with pytest.raises(ValueError):
                self.api.add_manual('d1', 0, [0, 0, 0.2, 0.2])
        finally:
            self.api._state.busy = False

    @invariant()
    def review_matches_independent_model(self):
        detail = self.api.details('d1')
        assert len(detail['findings']) == len(self.model)
        for actual, expected in zip(detail['findings'], self.model, strict=True):
            assert actual['token'] == expected['token'] and actual['enabled'] == expected['enabled']
            assert actual['view'][0] == pytest.approx(expected['rect'])
        assert self.doc.revision == self.revision
        assert detail['saved'] == (self.saved == self.revision)
        assert detail['history'] == {'undo': bool(self.undo), 'redo': bool(self.redo)}
        ids = [finding.id for finding in self.doc.analysis.findings]
        assert len(ids) == len(set(ids))

    def teardown(self):
        self.api.shutdown()
        self.folder.cleanup()


TestReviewSequences = ReviewSequences.TestCase
TestReviewSequences.settings = settings(max_examples=40, stateful_step_count=30, deadline=None, derandomize=True)
