#!/usr/bin/python2.7
# -*- coding: utf-8 -*-
"""
Created on Thu Nov 12 23:54:03 2015

@author: eladn
"""

import numpy as np
import sys
import os
import argparse
import pandas as pd
from progressbar import ProgressBar

base_path = os.path.split(os.path.realpath(__file__))[0]
sys.path.append(base_path)
from openbis import download_data_profiles

# script parameters (as determined by Mattia)
MIN_PEAK_SIZE = 5000
MAX_MZ_DIFFERENCE = 0.003
REF_MASS_RANGE = (50, 1000)
REFERENCE_MASS_FNAME = os.path.join(base_path, 'EMDTB.csv')
if not os.path.exists(REFERENCE_MASS_FNAME):
    raise Exception('Cannot locate the CSV file containing reference masses: '
                    + REFERENCE_MASS_FNAME)

def findpeaks(a):
    """
    Returns:
        list of indices of the local maxima in a 1D array 'a'. A local peak is 
        larger than its two neighboring samples. Endpoints are excluded.
        If a peak is flat, the function returns only the point with the lowest index.
    """
    tmp = np.diff(np.sign(np.diff(a.flat)))
    return np.where(tmp == -2)[0] + 1

parser = argparse.ArgumentParser(description='Download FIA raw data from openBIS')
parser.add_argument('exp_code', type=str,
                    help='the openBIS experiment ID')
parser.add_argument('-o', dest='output_fname', type=str, default=None,
                    help='a filename for writing the output')
args = parser.parse_args()

dataProfiles = download_data_profiles(args.exp_code)
dsSampleCodes = sorted(dataProfiles.keys())
n_samples = len(dsSampleCodes)

# allPeaks is a list of matrices (one per sample) of the ion mz and intensity
# only for the peaks (i.e. local maxima)
allPeaks = {}

#%% identify peaks (local maxima)
sys.stderr.write('\nCentroids identification\n')
with ProgressBar(max_value=n_samples) as progress:
    for i, s in enumerate(dsSampleCodes):
        progress.update(i)

        # find all the values that are local maxima and pass the threshold
        idxs = findpeaks(dataProfiles[s][:, 1])
        idxs = filter(lambda j : dataProfiles[s][j, 1] >= MIN_PEAK_SIZE, idxs)
        allPeaks[s] = dataProfiles[s][idxs, :]

#%% Use the reference table to associate peaks to compounds, by minimum mass distance
sys.stderr.write('\nMetabolites identification\n')

reference_df = pd.DataFrame.from_csv(REFERENCE_MASS_FNAME, index_col=None)

# subtract the mass of H+ (i.e. look for deprotonated masses)
proton_mass = reference_df.loc[0, 'mass']

# keep only ions in the relevant range for FIA
compound_df = reference_df[(REF_MASS_RANGE[0] < reference_df['mass']) &
                           (REF_MASS_RANGE[1] > reference_df['mass'])]

# peak_masses[i, j] will contain the exact mass of the peak which is closest
# to reference 'j' in sample 'i'. If there is no peak which is close enough
# (i.e. in the range of MAX_MZ_DIFFERENCE), the value will be NaN
# peak_indices[i, j] will contain the index of that peak in 'allPeaks[i]'
peak_masses  = pd.DataFrame(index=reference_df.index, columns=dsSampleCodes,
                            dtype=np.single)
peak_indices = pd.DataFrame(index=reference_df.index, columns=dsSampleCodes,
                            dtype=int)
with ProgressBar(max_value=n_samples) as progress:
    for i, s in enumerate(dsSampleCodes):
        progress.update(i)
        for j, refmass in reference_df['mass'].iteritems():
            diffs = abs(allPeaks[s][:, 0] + proton_mass - refmass)
            peak_idx = np.argmin(diffs)
            if diffs[peak_idx] <= MAX_MZ_DIFFERENCE:
                peak_indices.loc[j, s] = peak_idx
                peak_masses.loc[j, s] = allPeaks[s][peak_idx, 0]
            else:
                peak_indices.loc[j, s] = -1
                peak_masses.loc[j, s] = np.nan

# keep only the reference masses that actually have a 'hit' in at least one
# of the samples, and calculate the median of all samples where a peak was 
# associated with this mass
ref_hits      = (peak_indices != -1).any(1)
peak_indices  = peak_indices.loc[ref_hits, :]
median_masses = peak_masses.loc[ref_hits, :].median(1)
compound_df   = compound_df.loc[ref_hits, :]

#%%
sys.stderr.write('\nCreating final matrix\n')
 
# merged[i, j] will contain the intensity of the peak which was associated with
# reference mass 'j' in sample 'i'. If there wasn't any close enough mass, 
# we take the median mass of the ions associated with this reference mass
# across all other samples, and find the ion closest to the median (even if 
# it is not actually a peak).

merged = pd.DataFrame(index=compound_df.index, columns=dsSampleCodes,
                      dtype=np.single)
with ProgressBar(max_value=n_samples) as progress:
    for i, s in enumerate(dsSampleCodes):
        progress.update(i)
        for j, median_mass in median_masses.iteritems():
            peak_idx = peak_indices.loc[j, s]
            if peak_idx != -1:
                # if there is a peak associated with the metabolite,
                # get the intensity of that peak
                merged.loc[j, s] = allPeaks[s][peak_idx, 1]
            else:
                # otherwise, get the intensity from the closest mz in the raw data
                idx = np.argmin(np.abs(median_mass - dataProfiles[s][:, 0]))
                merged.loc[j, s] = dataProfiles[s][idx, 1]

merged = compound_df.join(merged)

#%%
if args.output_fname is None:
    args.output_fname = args.exp_code + '.csv'

sys.stderr.write('\nWriting results to output CSV file "%s" ... ' % args.output_fname)
merged.to_csv(args.output_fname)
sys.stderr.write('[DONE]\n')
