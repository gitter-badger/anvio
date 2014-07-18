# -*- coding: utf-8

# Copyright (C) 2014, A. Murat Eren
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# Please read the COPYING file.

import copy
import numpy

from PaPi.utils import KMers
from PaPi.entropy import ColumnEntropyProfile

kmers = KMers()


class Contig:
    def __init__(self, name):
        self.name = name
        self.splits = []
        self.length = 0
        self.mean_coverage = 0.0
        self.tnf = {}


    def analyze_coverage(self, bam, progress):
        for split in self.splits:
            progress.update('Coverage (split: %d of %d)' % (split.order, len(self.splits)))
            split.coverage = Coverage(split, bam)


    def analyze_auxiliary(self, bam, progress):
        for split in self.splits:
            progress.update('Auxiliary stats (split: %d of %d) CMC: %.1f :: SMC: %.1f'\
                                 % (split.order, len(self.splits), self.mean_coverage, split.coverage.mean))
            split.auxiliary = Auxiliary(split, bam)


    def analyze_composition(self, bam, progress):
        for split in self.splits:
            progress.update('Composition (split: %d of %d)' % (split.order, len(self.splits)))
            split.composition = Composition(split, bam)


    def get_rep_seq(self):
        return ''.join([s.auxiliary.rep_seq for s in self.splits])


    def analyze_tnf(self, progress):
        progress.update('TNF')
        rep_seq = self.get_rep_seq()

        if rep_seq.count('N') == len(rep_seq):
            # we don't want all kmer freq values to be zero. so the distance
            # metrics wouldn't go crazy. instead we fill it with 1. which
            # doesn't affect relative distances.
            words = kmers.kmers[kmers.k]
            self.tnf = dict(zip(words, [1] * len(words)))
        else:
            self.tnf = kmers.get_kmer_frequency(rep_seq)

    def get_mean_self_coverage(self, progress):
        progress.update('Computing mean coverage for contig from splits')
        self.mean_coverage = sum([split.coverage.mean * split.length / self.length for split in self.splits])
        return self.mean_coverage 


class Split:
    def __init__(self, parent, order, start, end):
        self.name = '_'.join([parent, 'split', '%04d' % order, start.__str__(), end.__str__()])
        self.parent = parent
        self.end = end
        self.order = order
        self.start = start
        self.length = end - start
        self.explicit_length = 0

        #progress.update('Analyzing coverage ...')
        #self.coverage = Coverage(self, bam.pileup(parent, start, end))
        #progress.update('Analyzing auxiliary stats ...')
        #self.auxiliary = Auxiliary(self, bam.pileup(parent, start, end))
        #progress.update('Analyzing composition ...')
        #self.composition = Composition(self, bam.pileup(parent, start, end))


class Auxiliary:
    def __init__(self, split, bam):
        self.rep_seq = ''
        self.split = split
        self.average_entropy = 0.0
        self.average_normalized_entropy = 0.0

        self.run(bam)


    def run(self, bam):
        column_entropy_profile = {}
        for pileupcolumn in bam.pileup(self.split.parent, self.split.start, self.split.end):
            if pileupcolumn.pos < self.split.start or pileupcolumn.pos >= self.split.end:
                continue

            column = ''.join([pileupread.alignment.seq[pileupread.qpos] for pileupread in pileupcolumn.pileups])

            column_entropy_profile[pileupcolumn.pos] = ColumnEntropyProfile(column,
                                                        pileupcolumn.pos,
                                                        self.split.coverage.max,
                                                        self.split.coverage.median)


        self.average_entropy = sum(e.entropy * 100.0 for e in column_entropy_profile.values()) / self.split.length
        self.average_normalized_entropy = sum(e.normalized_entropy * 100.0 for e in column_entropy_profile.values()) / self.split.length

        for i in range(self.split.start, self.split.end):
            if column_entropy_profile.has_key(i):
                self.rep_seq += column_entropy_profile[i].consensus_nucleotide
            else:
                self.rep_seq += 'N'


class Composition:
    def __init__(self, split, bam):
        self.split = split
        self.A = 0
        self.T = 0
        self.C = 0
        self.G = 0
        self.N = 0
        self.GC_content = 0.0

        self.report()

    def report(self):
        sequence = self.split.auxiliary.rep_seq
        raw_length = len(sequence)
        
        self.A = sequence.count('A')
        self.T = sequence.count('T')
        self.C = sequence.count('C')
        self.G = sequence.count('G')
        self.N = raw_length - (self.A + self.T + self.C + self.G)
    
        length = raw_length - self.N
    
        if not length:
            # sequence is composed of only N's
            self.GC_content = 0.0
        else:
            self.GC_content = (self.G + self.C) * 1.0 / length

        #self.composition['tnf'] = kmers.get_kmer_frequency(sequence)
    

class Coverage:
    def __init__(self, split, bam):
        self.split = split
        self.c = []
        self.min = 0
        self.max = 0
        self.std = 0.0
        self.mean = 0.0
        self.median = 0.0

        self.run(bam)


    def run(self, bam):
        for pileupcolumn in bam.pileup(self.split.parent, self.split.start, self.split.end):
            if pileupcolumn.pos < self.split.start or pileupcolumn.pos >= self.split.end:
                continue

            self.c.append(pileupcolumn.n)

        if self.c:
            self.split.explicit_length = len(self.c) 
            self.min = numpy.min(self.c)
            self.max = numpy.max(self.c)
            self.median = numpy.median(self.c)
            self.mean = numpy.mean(self.c)
            self.std = numpy.std(self.c)