# -*- coding: utf-8 -*-

import difflib
import numpy as np
import os
import SimpleITK as sitk
import scipy.spatial
from scipy.spatial.distance import directed_hausdorff


labels = {
          0: 'Background',
          1: 'Cortical gray matter',
          2: 'Basal ganglia',
          3: 'White matter',
          4: 'White matter lesions',
          5: 'Cerebrospinal fluid in the extracerebral space',
          6: 'Ventricles',
          7: 'Cerebellum',
          8: 'Brain stem',
          # The two labels below are ignored:
          # 9: 'Infarction',
          # 10: 'Other',
          }


def evaluate_stats(test_idx):

    for i in range(len(test_idx)):
        test_filename = "../data/mrbrains/test/"+str(test_idx[i])+"/segm.nii.gz"
        result_filename = "../results/result_"+str(test_idx[i])+".nii.gz"
        test_file, result_file = getImages(test_filename,result_filename)
        dsc = getDSC(test_file,result_file)
        h95 = getHausdorff(test_file,result_file)
        vs = getVS(test_file,result_file)

        print('Dice', dsc, '(higher is better, max=1)')
        print('HD', h95, 'mm', '(lower is better, min=0)')
        print('VS', vs, '(higher is better, max=1)')



def getImages(testFilename, resultFilename):
    """Return the test and result images, thresholded and pathology masked."""
    testImage = sitk.ReadImage(testFilename)
    resultImage = sitk.ReadImage(resultFilename)

    # Check for equality
    assert testImage.GetSize() == resultImage.GetSize()

    # Get meta data from the test-image, needed for some sitk methods that check this
    resultImage.CopyInformation(testImage)

    # Remove pathology from the test and result images, since we don't evaluate on that
    pathologyImage = sitk.BinaryThreshold(testImage, 9, 11, 0, 1)  # pathology == 9 or 10

    maskedTestImage = sitk.Mask(testImage, pathologyImage)  # tissue    == 1 --  8
    maskedResultImage = sitk.Mask(resultImage, pathologyImage)

    # Force integer
    if not 'integer' in maskedResultImage.GetPixelIDTypeAsString():
        maskedResultImage = sitk.Cast(maskedResultImage, sitk.sitkUInt8)

    return maskedTestImage, maskedResultImage


def getDSC(testImage, resultImage):
    """Compute the Dice Similarity Coefficient."""
    dsc = dict()
    for k in labels.keys():
        testArray = sitk.GetArrayFromImage(sitk.BinaryThreshold(testImage, k, k, 1, 0)).flatten()
        resultArray = sitk.GetArrayFromImage(sitk.BinaryThreshold(resultImage, k, k, 1, 0)).flatten()

        # similarity = 1.0 - dissimilarity
        # scipy.spatial.distance.dice raises a ZeroDivisionError if both arrays contain only zeros.
        try:
            dsc[k] = 1.0 - scipy.spatial.distance.dice(testArray, resultArray)
        except ZeroDivisionError:
            dsc[k] = None

    return dsc


def getHausdorff(testImage, resultImage):
    """Compute the 95% Hausdorff distance."""
    hd = dict()
    for k in labels.keys():
        lTestImage = sitk.BinaryThreshold(testImage, k, k, 1, 0)
        lResultImage = sitk.BinaryThreshold(resultImage, k, k, 1, 0)

        # Hausdorff distance is only defined when something is detected
        statistics = sitk.StatisticsImageFilter()
        statistics.Execute(lTestImage)
        lTestSum = statistics.GetSum()
        statistics.Execute(lResultImage)
        lResultSum = statistics.GetSum()
        if lTestSum == 0 or lResultSum == 0:
            hd[k] = None
            continue

        # Edge detection is done by ORIGINAL - ERODED, keeping the outer boundaries of lesions. Erosion is performed in 2D
        eTestImage = sitk.BinaryErode(lTestImage, (1, 1, 0))
        eResultImage = sitk.BinaryErode(lResultImage, (1, 1, 0))

        hTestImage = sitk.Subtract(lTestImage, eTestImage)
        hResultImage = sitk.Subtract(lResultImage, eResultImage)

        hTestArray = sitk.GetArrayFromImage(hTestImage)
        hResultArray = sitk.GetArrayFromImage(hResultImage)

        # Convert voxel location to world coordinates. Use the coordinate system of the test image
        # np.nonzero   = elements of the boundary in numpy order (zyx)
        # np.flipud    = elements in xyz order
        # np.transpose = create tuples (x,y,z)
        # testImage.TransformIndexToPhysicalPoint converts (xyz) to world coordinates (in mm)
        # (Simple)ITK does not accept all Numpy arrays; therefore we need to convert the coordinate tuples into a Python list before passing them to TransformIndexToPhysicalPoint().
        testCoordinates = [testImage.TransformIndexToPhysicalPoint(x.tolist()) for x in
                           np.transpose(np.flipud(np.nonzero(hTestArray)))]
        resultCoordinates = [resultImage.TransformIndexToPhysicalPoint(x.tolist()) for x in
                             np.transpose(np.flipud(np.nonzero(hResultArray)))]

        # Use a kd-tree for fast spatial search
        def getDistancesFromAtoB(a, b):
            kdTree = scipy.spatial.KDTree(a, leafsize=100)
            return kdTree.query(b, k=1, eps=0, p=2)[0]

        # Compute distances from test to result and vice versa.
        dTestToResult = getDistancesFromAtoB(testCoordinates, resultCoordinates)
        dResultToTest = getDistancesFromAtoB(resultCoordinates, testCoordinates)
        hd[k] = max(np.percentile(dTestToResult, 95), np.percentile(dResultToTest, 95))

    return hd


def getVS(testImage, resultImage):
    """Volume similarity.
    VS = 1 - abs(A - B) / (A + B)
    A = ground truth in ML
    B = participant segmentation in ML
    """
    # Compute statistics of both images
    testStatistics = sitk.StatisticsImageFilter()
    resultStatistics = sitk.StatisticsImageFilter()

    vs = dict()
    for k in labels.keys():
        testStatistics.Execute(sitk.BinaryThreshold(testImage, k, k, 1, 0))
        resultStatistics.Execute(sitk.BinaryThreshold(resultImage, k, k, 1, 0))

        numerator = abs(testStatistics.GetSum() - resultStatistics.GetSum())
        denominator = testStatistics.GetSum() + resultStatistics.GetSum()

        if denominator > 0:
            vs[k] = 1 - float(numerator) / denominator
        else:
            vs[k] = None

    return vs

def get_dice_score(lab2d, pred2d):
    """Compute the Dice Similarity Coefficient."""

    dsc = dict()
    for k in range(9):
        # similarity = 1.0 - dissimilarity
        # scipy.spatial.distance.dice raises a ZeroDivisionError if both arrays contain only zeros.
        try:
            dsc[k] = 1.0 - scipy.spatial.distance.dice(np.where(lab2d==k,lab2d,0), np.where(pred2d==k,pred2d,0))
        except ZeroDivisionError:
            print("DIvision by Zero")
            dsc[k] = 0
    return dsc

def getDistancesFromAtoB(a, b):
    kdTree = scipy.spatial.KDTree(a, leafsize=100)
    return kdTree.query(b, k=1, eps=0, p=2)[0]


def get_hausdorff_distance(lab2d, pred2d):
    """Compute the Hausdorff Distance."""

    h_dist = dict()
    for k in range(9):
        gt_val = np.reshape(np.where(lab2d == k, lab2d, 0), [220, 220, 48])
        pred_val = np.reshape(np.where(pred2d == k, pred2d, 0), [220, 220, 48])
        # Compute distances from test to result and vice versa.
        dTestToResult = getDistancesFromAtoB(gt_val, pred_val)
        dResultToTest = getDistancesFromAtoB(pred_val, gt_val)
        h_dist[k] = max(np.percentile(dTestToResult, 95), np.percentile(dResultToTest, 95))


        # gt_val = np.reshape(np.where(lab2d==k,lab2d,0),[220,220,48])
        # pred_val = np.reshape(np.where(pred2d==k,pred2d,0),[220,220,48])
        # h_dist[k] = max(directed_hausdorff(u=gt_val, v=pred_val)[0],
        #                     directed_hausdorff(u=pred_val, v=gt_val)[0])
    return h_dist


def get_volumetric_symmetry(lab2d, pred2d):
    """Compute the volumetric symmetry"""

    vs = dict()
    for k in range(9):
        gt_labels = np.where(lab2d == k, lab2d, 0)
        pred_labels = np.where(pred2d==k,pred2d,0)

        numerator = abs(np.sum(gt_labels) - np.sum(pred_labels))
        denominator = np.sum(gt_labels) + np.sum(pred_labels)

        if denominator > 0:
            vs[k] = 1 - float(numerator) / denominator
        else:
            vs[k] = None

    return vs

if __name__ == '__main__':
    evaluate_stats(test_idx=[7, 14])