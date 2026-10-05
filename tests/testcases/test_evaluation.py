import backend.evaluation

import zipfile, tempfile, os
import PIL.Image
import numpy as np
import pytest
import csv
import io


def test_evaluate_single():
    ytrue = np.zeros([100,100], 'uint8')
    ytrue[:,:50] = 255
    ypred = np.zeros([100,100], 'uint8')
    ypred[:50]   = 255

    tmpdir    = tempfile.TemporaryDirectory()
    ytrue_png = os.path.join(tmpdir.name, 'AAA.png')
    ypred_png = os.path.join(tmpdir.name, 'AAA.tiff.segmentation.png')
    PIL.Image.fromarray(ytrue).save(ytrue_png)
    PIL.Image.fromarray(ypred).save(ypred_png)

    evresult = backend.evaluation.evaluate_single_file(ypred_png, ytrue_png)
    assert np.allclose(evresult['IoU'], 1/3)

    outputfile = os.path.join(tmpdir.name, 'evaluation.zip')
    backend.evaluation.save_evaluation_results([evresult], outputfile)
    assert os.path.exists(outputfile)
    with zipfile.ZipFile(outputfile) as archive:
        contents = archive.namelist()
        assert 'statistics.csv'    in contents
        csv_stats = archive.read('statistics.csv').decode('utf8').strip().split('\n')
        assert len(csv_stats) == 2
        assert csv_stats[0].startswith('#')
        assert csv_stats[1].split(',')[0].strip() == 'AAA.tiff'
        assert csv_stats[1].split(',')[4].strip() == '0.33'   #iou
        
        assert 'AAA.tiff/error_map.png' in contents



def test_evaluate_with_exclusionmask():
    ytrue = np.zeros([100,100,3], 'uint8')
    ytrue[:,:50] = 255
    ypred = np.zeros([100,100,3], 'uint8')
    ypred[:50]   = 255

    #exclusion mask
    ytrue[:,:25] = (255, 0, 0)
    ypred[:25]   = (255, 0, 0)

    tmpdir    = tempfile.TemporaryDirectory()
    ytrue_png = os.path.join(tmpdir.name, 'AAA.png')
    ypred_png = os.path.join(tmpdir.name, 'AAA.tiff.segmentation.png')
    PIL.Image.fromarray(ytrue).save(ytrue_png)
    PIL.Image.fromarray(ypred).save(ypred_png)

    evresult = backend.evaluation.evaluate_single_file(ypred_png, ytrue_png)
    assert np.allclose(evresult['IoU'], 625 / 4375)



def test_IoU():
    a = np.zeros([100,100])
    b = np.zeros([100,100])
    b[:50] = 1
    assert backend.evaluation.IoU(a,b) == 0

    c = np.zeros([100,100])
    c[:,:50] = 1
    assert np.allclose(backend.evaluation.IoU(c,b) , 1/3)


def test_error_map():
    ytrue = np.zeros([100,100])
    ytrue[:,:50] = 1
    ypred = np.zeros([100,100])
    ypred[:50] = 1

    errormap = backend.evaluation.create_error_map(ytrue, ypred)
    assert np.all(errormap[:50,:50] == (0,1,0)) #green true positive
    assert np.all(errormap[:50,50:] == (1,0,0)) #red   false positive
    assert np.all(errormap[50:,:50] == (0,0,1)) #blue  false negative
    assert np.all(errormap[50:,50:] == (0,0,0)) #black true negative


def test_empty_masks_have_explicit_undefined_metrics():
    empty = np.zeros((4, 4), bool)
    metrics = backend.evaluation.precision_recall(empty, empty)
    assert backend.evaluation.IoU(empty, empty) is None
    assert metrics == {'TP': 0, 'FP': 0, 'FN': 0, 'precision': None, 'recall': None, 'F1': None}
    result = dict(metrics, IoU=None, predictionfile='sample,one.segmentation.png')
    rows = list(csv.reader(io.StringIO(backend.evaluation.results_to_csv([result]))))
    assert rows[1] == ['sample,one', '0', '0', '0', 'N/A', 'N/A', 'N/A', 'N/A']


def test_one_empty_mask_reports_zero_overlap_without_division_warnings():
    empty, full = np.zeros((4, 4), bool), np.ones((4, 4), bool)
    with np.errstate(all='raise'):
        missed = backend.evaluation.precision_recall(full, empty)
        false = backend.evaluation.precision_recall(empty, full)
    assert missed['precision'] is None and missed['recall'] == 0 and missed['F1'] == 0
    assert false['precision'] == 0 and false['recall'] is None and false['F1'] == 0


@pytest.mark.parametrize('function', [backend.evaluation.IoU, backend.evaluation.precision_recall, backend.evaluation.create_error_map])
def test_evaluation_rejects_broadcasting_and_non_2d_masks(function):
    for wrong in [np.zeros((1, 4)), np.zeros((4, 4, 1))]:
        with pytest.raises(ValueError, match='same two-dimensional shape'):
            function(np.zeros((4, 4)), wrong)
