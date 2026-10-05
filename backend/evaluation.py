import numpy as np
import PIL.Image
import zipfile, os, io
import csv
import typing as tp



def evaluate_single_file(predictionfile:str, annotationfile:str) -> dict:
    ypred = load_segmentationfile(predictionfile)
    ytrue = load_segmentationfile(annotationfile)

    result = {
        'IoU'                : IoU(ytrue, ypred),
        'error_map'          : create_error_map(ytrue, ypred),
        'predictionfile'     : os.path.basename(predictionfile),
        'annotationfile'     : os.path.basename(annotationfile),
    }
    result.update(precision_recall(ytrue, ypred))
    return result

def load_segmentationfile(filename:str) -> np.array:
    image = PIL.Image.open(filename).convert('RGB') * np.uint8(1)
    return np.all(image == (255, 255, 255), axis=-1)

def save_evaluation_results(results:list, destination:str):
    csv_text = results_to_csv(results)
    with zipfile.ZipFile(destination, 'w') as archive:
        archive.writestr('statistics.csv', csv_text)
    
        for r in results:
            filename  = r['predictionfile'].replace('.segmentation.png','')
            outpath   = os.path.join(filename, 'error_map.png')
            archive.open(outpath, 'w').write(error_map_to_png(r['error_map']))


def _mask_pair(a, b):
    a, b = np.asarray(a, bool), np.asarray(b, bool)
    if a.ndim != 2 or b.ndim != 2 or a.shape != b.shape:
        raise ValueError('Evaluation requires two masks with the same two-dimensional shape.')
    return a, b


def _ratio(numerator, denominator):
    return float(numerator) / float(denominator) if denominator else None


def IoU(a:np.array, b:np.array) -> tp.Optional[float]:
    a, b = _mask_pair(a, b)
    intersection = a & b
    union        = a | b
    return _ratio(intersection.sum(), union.sum())

def precision_recall(ytrue:np.array, ypred:np.array) -> dict:
    ytrue, ypred = _mask_pair(ytrue, ypred)
    TP      = int((ypred & ytrue).sum())
    FP      = int((ypred & (~ytrue)).sum())
    FN      = int(((~ypred) & ytrue).sum())
    precision = _ratio(TP, TP + FP)
    recall    = _ratio(TP, TP + FN)
    f1        = _ratio(2 * TP, 2 * TP + FP + FN)
    return {
        'TP':TP, 
        'FP':FP, 
        'FN':FN, 
        'precision': precision, 
        'recall':    recall,
        'F1':        f1,
    }



RED   = (1.0, 0.0, 0.0)
GREEN = (0.0, 1.0, 0.0)
BLUE  = (0.0, 0.0, 1.0)

def create_error_map(ytrue:np.array, ypred:np.array) -> np.array:
    ytrue, ypred = _mask_pair(ytrue, ypred)
    TP     =  ypred &  ytrue
    FP     =  ypred & ~ytrue
    FN     = ~ypred &  ytrue

    result = (
          TP[...,None] * GREEN
        + FP[...,None] * RED
        + FN[...,None] * BLUE
    )
    return result


def results_to_csv(results:list) -> str:
    def metric(value):
        return 'N/A' if value is None else '{:.2f}'.format(value)
    csv_header = ['#Filename', 'True Positives (px)', 'False Positives (px)', 'False Negatives (px)', 'IoU', 'Precision', 'Recall', 'F1']
    csv_data   = []
    for r in results:
        filename  = r['predictionfile'].replace('.segmentation.png','')
        csv_data += [[
            filename,
            f"{r['TP']:d}",
            f"{r['FP']:d}",
            f"{r['FN']:d}",
            metric(r['IoU']),
            metric(r['precision']),
            metric(r['recall']),
            metric(r['F1']),
        ]]
        assert len(csv_data[-1]) == len(csv_header)
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerow(csv_header)
    writer.writerows(csv_data)
    return buffer.getvalue()
    
def error_map_to_png(error_map:np.array) -> bytes:
    error_map = PIL.Image.fromarray( (error_map*255).astype('uint8') )
    buffer    = io.BytesIO()
    error_map.save(buffer, format='png')
    buffer.seek(0);
    return buffer.read()
