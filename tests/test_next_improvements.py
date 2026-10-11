"""Precise integrity errors, early preview rejection and independent occurrence geometry."""
from types import SimpleNamespace
from unittest.mock import Mock
import pymupdf
import pytest
from app.engine.types import Finding
from tests import test_review_fixes
from tools.occurrence_evaluation import annotate, coverage, project, rect_covered
from tools.evaluation_corpus import challenging_documents

@pytest.fixture
def bridge():
    yield from test_review_fixes.bridge.__wrapped__()

@pytest.mark.parametrize('message', ['Otro proceso sigue utilizando los modelos', 'Archivos alterados: fictitious', 'No se pudo comprobar la integridad'])
def test_processing_keeps_exact_integrity_reason(bridge, message):
    api, _ = bridge
    api.status = Mock(return_value={'blocked': True, 'errors': {'integrity': message}})
    api._engine.call = Mock()
    assert not api.process({})
    assert api.poll()['progress']['message'] == message and not api.poll()['busy']
    api._engine.call.assert_not_called()

@pytest.mark.parametrize('page,which,width', [(True,'result',1100),(-1,'result',1100),(1,'result',1100),
                                            (0,'unknown',1100),(0,'result',False),(0,'result',3301)])
def test_invalid_preview_does_not_build_or_render(bridge, page, which, width):
    api, doc = bridge
    api._light.call = Mock()
    with pytest.raises(ValueError):
        api.page_image(doc.id, page, which, {'previewWidth': width})
    api._light.call.assert_not_called()
    assert doc.preview_bytes is None and doc.preview_key == ''


def test_all_repetitions_and_pages_require_positional_coverage():
    with pymupdf.open() as pdf:
        for _ in range(2):
            page = pdf.new_page()
            page.insert_text((40,80), 'Fictitious Name')
            page.insert_text((40,180), 'Fictitious Name')
        truth = annotate(pdf.tobytes(), [{'type':'name','value':'Fictitious Name'}])[0]
    assert len(truth['occurrences']) == 4
    occurrence = truth['occurrences'][0]
    findings = [Finding('first',0,'name','Fictitious Name',occurrence['rects'],1,'text')]
    assert coverage(SimpleNamespace(findings=findings),truth) == (1,4)
    findings[0].enabled = False
    assert coverage(SimpleNamespace(findings=findings),truth) == (0,4)


def test_vertical_partial_coverage_and_overlapping_marks_do_not_count_twice():
    findings = [Finding('first',0,'manual',None,[(0,0,100,5)],1,'manual')]
    analysis = SimpleNamespace(findings=findings)
    assert not rect_covered(analysis,(0,0,100,20),0)
    findings.append(Finding('second',0,'manual',None,[(0,5,100,20)],1,'manual'))
    assert rect_covered(analysis,(0,0,100,20),0)
    assert not rect_covered(analysis,(0,0,100,20),1)


def test_scan_and_photo_annotations_include_all_five_layout_occurrences():
    for kind, _, data, truth in challenging_documents(2027, include_scanned=True):
        if kind == 'synthetic-handwriting':
            continue
        assert len(truth[0]['occurrences']) == 5
        with pymupdf.open('pdf',data) as doc:
            assert all(len(o['rects']) > 0 and o['page'] < len(doc) for o in truth[0]['occurrences'])


@pytest.mark.parametrize('angle,affine,expected', [(0, None, [90,30,110,50]),
                                                 (90, None, [80,40,100,60]),
                                                 (0, (1,0.25,0,0,1,0), [77.5,30,102.5,50])])
def test_positional_transform_matches_independent_geometry(angle, affine, expected):
    from PIL import Image
    import io
    image = io.BytesIO()
    Image.new('RGB', (200,100), 'white').save(image, 'PNG')
    with pymupdf.open() as source, pymupdf.open() as target:
        original = source.new_page(width=200, height=100)
        raster = target.new_page(width=200, height=100)
        raster.insert_image(raster.rect, stream=image.getvalue())
        truth = [{'occurrences': [{'page': 0, 'rects': [[90,30,110,50]]}]}]
        actual = project(truth, original, raster, (200,100), angle=angle, affine=affine)
        assert actual[0]['occurrences'][0]['rects'][0] == pytest.approx(expected)
        assert truth[0]['occurrences'][0]['rects'][0] == [90,30,110,50]
