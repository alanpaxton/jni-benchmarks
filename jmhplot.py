#!/usr/bin/env python3
#
# Copyright © 2016, Evolved Binary Ltd
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the <organization> nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

import argparse
from datetime import datetime
from collections import namedtuple
import pathlib
from typing import List, NewType, Sequence, Tuple

import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from pandas.core.frame import DataFrame
import re
from sys import maxsize

# Types
Params = NewType('Params', dict[str, str])
BMParams = namedtuple("BMParams", "primary secondary")
Benchmark = NewType('Benchmark', str)
BMResult = namedtuple("BMResult", "value, score, error")
ResultSet = NewType('ResultSet', dict[Benchmark, Sequence[BMResult]])
ResultSets = NewType('ResultSets', dict[Tuple, ResultSet])

const_datetime_str = datetime.today().isoformat()


class BenchmarkError(Exception):
    """Base class for exceptions in this module."""

    def __init__(self, message: str):
        self.message = message


# read files, merge allegedly similar results
#
# return a single data frame
#


def normalize_data_frame_from_path(path: pathlib.Path):
    files = []
    if path.is_dir():
        files = sorted(path.rglob("*.csv"))
    else:
        files.append(path)

    normalized = None
    for file in files:
        df = pd.read_csv(file)
        # every 9th line is the interesting one, discard the rest
        df = df.iloc[::9, :]
        df["Benchmark"] = df["Benchmark"].apply(lambda x: x.split('.')[-1])
        if normalized is None:
            normalized = df
        else:
            normalized = pd.merge(normalized, df)
    if normalized is None:
        raise BenchmarkError(f'No csv file(s) found at {path}')
    return normalized

# Decide which columns are params (they are labelled "Param: <name>")
# return a map of { <name> : <label> } e.g. { "valueSize": "Param: valueSize", "checksum": "Param: checksum"}


def extract_params(dataframe: DataFrame) -> Params:
    params = {}
    for column in dataframe.columns:
        fields = column.split(':')
        if len(fields) == 2 and fields[0] == 'Param':
            params[fields[1].strip()] = column

    return params

# Separate the param map into a single entry dictionary (primary)
# and a multi-entry (all the rest)


def split_params(params: Params, primary_param_name: str) -> BMParams:

    if not primary_param_name in params.keys():
        raise BenchmarkError(
            f'Missing {primary_param_name} in params {params}')
    primary_params = {primary_param_name: params[primary_param_name]}

    del params[primary_param_name]
    secondary_params = params

    return BMParams(primary=primary_params, secondary=secondary_params)


# Dictionary indexed by the tuple of secondary parameter values
# For the fixed tuple, indexed by each benchmark
# within each benchmark, a namedtuple of { value:, score:, error:, } for the value of the primary parameter, its score and its error

def extract_results_per_param(dataframe: DataFrame, params: BMParams) -> ResultSets:
    resultSets: ResultSets = {}
    for _, row in dataframe.iterrows():
        secondaryTuple = tuple_of_secondary_values(params, row)
        if not secondaryTuple in resultSets.keys():
            resultSets[secondaryTuple] = {}
        if not row['Benchmark'] in resultSets[secondaryTuple].keys():
            resultSets[secondaryTuple][row['Benchmark']] = []
        for _, column in params.primary.items():
            entry = BMResult(
                value=row[column], score=row['Score'], error=row['Score Error (99.9%)'])
            resultSets[secondaryTuple][row['Benchmark']].append(entry)

    return resultSets


def tuple_of_secondary_values(params: BMParams, row: np.row_stack) -> Tuple:
    secondaryValues = []
    for _, column in params.secondary.items():
        secondaryValues.append(row[column])
    return tuple(secondaryValues)


def tuple_of_secondary_keys(params: BMParams) -> Tuple:
    secondaryKeys = []
    for key, _ in params.secondary.items():
        secondaryKeys.append(key)
    return tuple(secondaryKeys)


def plot_all_results(params: BMParams, resultSets: ResultSets, path, report_benchmarks: str) -> None:
    indexKeys = tuple_of_secondary_keys(params)
    for indexTuple, resultSet in resultSets.items():
        plot_result_set(indexKeys, indexTuple, resultSet,
                        path, report_benchmarks)


def plot_result_axis_errorbars(ax, resultSet: ResultSet) -> None:
    ax.set_xscale('log')
    ax.set_yscale('log')

    uplimits = [True, False] * 5
    lolimits = [False, True] * 5

    for benchmark, results in resultSet.items():
        count = len(results)
        values = [result.value for result in results]
        offsets = list(range(count))
        scores = [result.score for result in results]
        errors = [result.error for result in results]

        swaplimits = uplimits
        uplimits = lolimits
        lolimits = swaplimits

        ax.errorbar(np.array(values), np.array(scores),
                    uplims=uplimits[:count], lolims=lolimits[:count],
                    yerr=np.array(errors), label=benchmark, capsize=6.0, capthick=1.5)


def plot_result_axis_bars(ax, resultSet: ResultSet) -> None:

    ax.set_xscale('log')

    barCount = 0
    for index, result in resultSet.items():
        barCount = len(result)
        break

    widths = [0 for _ in range(barCount+1)]
    bmIndex = -(barCount/2)

    for benchmark, results in resultSet.items():

        # The first iteration will have widths == [0,0,...] so will mimic bmIndex==0, so don't do it twice...
        if bmIndex == 0:
            bmIndex = bmIndex + 1

        xs = [result.value for result in results]
        pairs = list(zip(widths, results))
        x2s = [vw[1].value + vw[0]*0.67*bmIndex for vw in pairs]
        ys = [result.score for result in results]

        bottoms = [result.score - result.error/2 for result in results]
        heights = [result.error for result in results]
        widths = [result.value/(barCount*3) for result in results]
        ax.bar(x=x2s, bottom=bottoms, height=heights, alpha=0.8,
               width=widths, label=benchmark)

        ax.plot(xs, ys)
        bmIndex = bmIndex + 1


def plot_result_set(indexKeys: Tuple, indexTuple: Tuple, resultSet: ResultSet, path: pathlib.Path, report_benchmarks: str):
    fig = plt.figure(num=None, figsize=(18, 12), dpi=80,
                     facecolor='w', edgecolor='k')
    ax = plt.subplot()

    plot_result_axis_bars(ax, resultSet)

    plt.title(f'{str(indexKeys)}={str(indexTuple)}  {report_benchmarks}')
    plt.xlabel("X")
    plt.ylabel("t (ns)")
    plt.legend(loc='lower right')
    plt.grid(b='True', which='both')
    index_name = '_'.join([str(k) for k in list(indexTuple)])
    name = f'fig_{const_datetime_str}_{index_name}.png'

    if path.is_file():
        path = path.parent()
    fig.savefig(path.joinpath(name))


def filter_for_benchmarks(dataframe: DataFrame, report_benchmarks: str) -> DataFrame:

    if report_benchmarks is None or '' == report_benchmarks:
        return dataframe

    report_bms = report_benchmarks.split(',')
    pattern = re.compile(f'[A-Za-z0-9_\-+]')
    for report_bm in report_bms:
        if pattern.match(report_bm) is None:
            raise BenchmarkError(
                f'The benchmark pattern {report_bm} has non-alphanumeric characters')
    report_bms_translated = '|'.join(report_bms)

    pattern = re.compile(f'\S*({report_bms_translated})\S*')
    return dataframe[dataframe['Benchmark'].apply(
        lambda x: pattern.match(x) is not None)]


def filter_for_range(dataframe: DataFrame, primary_param_name: str, select_range: str) -> DataFrame:

    from_to = select_range.split('<')
    if len(from_to) != 2:
        return dataframe

    low = -maxsize
    high = maxsize
    try:
        if (len(from_to[0]) > 0):
            low = int(from_to[0])
        if (len(from_to[1]) > 0):
            high = int(from_to[1])
    except Exception as e:
        raise BenchmarkError(f'The range {from_to} is not valid')
    if not low <= high:
        raise BenchmarkError(f'The range {from_to} is not valid')

    return dataframe[dataframe[f'Param: {primary_param_name}'].apply(
        lambda x: int(x) >= low and int(x) <= high)]


def process_benchmarks(stringpath: str, primary_param_name: str, report_benchmarks: str, select_range: str) -> None:

    path = pathlib.Path(stringpath)
    if not path.exists():
        raise BenchmarkError(f'The file path {path} does not exist')

    dataframe = normalize_data_frame_from_path(path)
    if len(dataframe) == 0:
        raise BenchmarkError(
            f'0 results were read from the file(s) at {stringpath}')

    dataframe = filter_for_benchmarks(dataframe, report_benchmarks)
    if len(dataframe) == 0:
        raise BenchmarkError(
            f'0 results after filtering benchmarks {report_benchmarks}')

    dataframe = filter_for_range(dataframe, primary_param_name, select_range)
    if len(dataframe) == 0:
        raise BenchmarkError(
            f'0 results after filtering range {select_range}')

    params: BMParams = split_params(
        extract_params(dataframe), primary_param_name)
    resultSets = extract_results_per_param(dataframe, params)
    plot_all_results(params, resultSets, path, report_benchmarks)


# Columns:
# Benchmark	Mode	Threads	Samples	Score	Score Error (99.9%)	Unit	Param: valueSize

argDirectory = '/Users/alan/swProjects/evolvedBinary/jni-benchmarks/analysis/run5mac'
argParam = 'valueSize'
# or a subset of these to show the ones we want
reportBenchmarks = 'Direct,Byte,Unsafe,Critical'
reportBenchmarks = 'Buffer'
reportBenchmarks = ''

argRange = '1<4097'
argRange = '4096<'

# Example usage:
# python process_byte_array_benchmarks_results.py -p results_dir/ --param-name "Param: valueSize" --chart-title "Performance comparison of getting byte array with {} bytes via JNI"


def main():
    parser = argparse.ArgumentParser(
        description='Process JMH benchmarks result files (only SampleTime mode supported).')
    parser.add_argument('-p', '--path', type=str,
                        help='Path to the directory with benchmarking results generated by JMH run', default=argDirectory)
    parser.add_argument('-n', '--param-name', type=str,
                        help='Benchmarks parameter name for X-axis of graphs', default=argParam)
    parser.add_argument('-s', '--select-range', type=str,
                        help='Range of values to plot for benchmark parameter', default=argRange)
    parser.add_argument('-c', '--chart-title', type=str, help='Charts\' title',
                        default='Performance comparison of getting byte array with {} bytes via JNI')
    parser.add_argument('-r', '--report-benchmarks', type=str, help='Subset of benchmarks to display in chart',
                        default=reportBenchmarks)
    args = parser.parse_args()

    try:
        process_benchmarks(args.path, args.param_name,
                           args.report_benchmarks, args.select_range)
    except BenchmarkError as error:
        print(
            f'JMH process benchmarks ({pathlib.Path(__file__).name}) error: {error.message}')


if __name__ == "__main__":
    main()
