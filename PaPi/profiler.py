#!/usr/bin/env python
# -*- coding: utf-8

# Copyright (C) 2014, A. Murat Eren
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# Please read the COPYING file.

import os
import sys
import json
import numpy
import pysam
import random
import cPickle
import operator
import subprocess
import PaPi.utils as utils
from PaPi.utils import pretty_print as pp
from PaPi.contig_stats_essential import Essential
from PaPi.contig_stats_auxiliary import Auxiliary
from PaPi.contig_composition import Composition


class BAMProfiler:
    """Creates an über class for BAM file operations"""
    def __init__(self, args = None):
        if args:
            self.args = args
            self.input_file_path = args.input_file
            self.serialized_profile_path = args.profile
            self.output_directory = args.output_directory
            self.list_contigs_and_exit = args.list_contigs
            self.min_contig_length = args.min_contig_length
            self.min_mean_coverage = args.min_mean_coverage
            self.number_of_threads = 4 
            self.no_trehading = True

            if args.contigs:
                if os.path.exists(args.contigs):
                    self.contigs_of_interest = [c.strip() for c in open(args.contigs).readlines() if c.strip() and not c.startswith('#')]
                else:
                    self.contigs_of_interest = [c.strip() for c in args.contigs.split(',')] if args.contigs else None

            else:
                self.contigs_of_interest = None

        else:
            self.args = args
            self.input_file_path = None 
            self.serialized_profile_path = None 
            self.output_directory = None 
            self.list_contigs_and_exit = None 
            self.min_contig_length = 10000 
            self.min_mean_coverage = 10
            # FIXME: Parameterize these two:
            self.number_of_threads = 4 
            self.no_trehading = False

        self.bam = None
        self.references_dict = {}

        self.progress = utils.Progress()
        self.run = utils.Run()


    def _run(self):
        self.check_args()

        if self.input_file_path:
            self.init_profile_from_BAM()
            self.profile()
            self.store_profile()
        else:
            self.init_serialized_profile()

        self.report()

        runinfo_serialized = self.generate_output_destination('RUNINFO.cPickle')
        self.run.info('runinfo', runinfo_serialized)
        self.run.store_info_dict(runinfo_serialized)
        self.run.quit()


    def init_serialized_profile(self):
        self.progress.new('Init')
        self.progress.update('Reading serialized profile')

        
        self.references_dict = cPickle.load(open(self.serialized_profile_path))
        self.progress.end()
        self.run.info('profile_loaded_from', self.serialized_profile_path)

        self.references = self.references_dict.keys()
        self.lengths = [self.references_dict[reference]['essential']['length'] for reference in self.references]

        self.run.info('num_contigs', pp(len(self.references)))

        if self.list_contigs_and_exit:
            print "\nContigs in the file:\n"
            for (reference, length) in zip(self.references, self.lengths):
                print "\t- %s (%s)" % (reference, pp(int(length)))
            print
            sys.exit()

        if self.contigs_of_interest:
            indexes = [self.references.index(r) for r in self.contigs_of_interest if r in self.references]
            self.references = [self.references[i] for i in indexes]
            self.lengths = [self.lengths[i] for i in indexes]
            self.run.info('num_contigs_selected_for_analysis', pp(len(self.references)))

        contigs_longer_than_M = set()
        for i in range(0, len(self.references)):
            if self.lengths[i] > self.min_contig_length:
                contigs_longer_than_M.add(i)
        if not len(contigs_longer_than_M):
            raise utils.ConfigError, "0 contigs larger than %s nts." % pp(self.min_contig_length)
        else:
            self.references = [self.references[i] for i in contigs_longer_than_M]
            self.raw_lengths = [self.lengths[i] for i in contigs_longer_than_M]
            self.run.info('contigs_raw_longer_than_M', len(self.references))

        self.progress.new('Init')
        self.progress.update('Initializing the output directory ...')
        self.init_output_directory()
        self.progress.end()
        self.run.info('output_dir', self.output_directory)


    def init_profile_from_BAM(self):
        self.progress.new('Init')
        self.progress.update('Reading BAM File')
        self.bam = pysam.Samfile(self.input_file_path, 'rb')
        self.progress.end()
        self.run.info('input_bam', self.input_file_path)

        self.references = self.bam.references
        self.raw_lengths = self.bam.lengths

        try:
            self.num_reads_mapped = self.bam.mapped
        except ValueError:
            raise utils.ConfigError, "It seems the BAM file is not indexed. See 'papi-init-bam' script."

        self.progress.new('Init')
        self.progress.update('Initializing the output directory ...')
        self.init_output_directory()
        self.progress.end()

        runinfo = self.generate_output_destination('RUNINFO')
        self.run.init_info_file_obj(runinfo)
        self.run.info('output_dir', self.output_directory)

        self.run.info('total_reads_mapped', pp(int(self.num_reads_mapped)))
        self.run.info('num_contigs', pp(len(self.references)))

        if self.list_contigs_and_exit:
            print "\nContigs in the file:\n"
            for (reference, length) in zip(self.references, self.raw_lengths):
                print "\t- %s (%s)" % (reference, pp(int(length)))
            print
            sys.exit()

        if self.contigs_of_interest:
            indexes = [self.references.index(r) for r in self.contigs_of_interest if r in self.references]
            self.references = [self.references[i] for i in indexes]
            self.raw_lengths = [self.raw_lengths[i] for i in indexes]
            self.run.info('num_contigs_selected_for_analysis', pp(len(self.references)))

        contigs_longer_than_M = set()
        for i in range(0, len(self.references)):
            if self.raw_lengths[i] > self.min_contig_length:
                contigs_longer_than_M.add(i)
        if not len(contigs_longer_than_M):
            raise utils.ConfigError, "0 contigs larger than %s nts." % pp(self.min_contig_length)
        else:
            self.references = [self.references[i] for i in contigs_longer_than_M]
            self.raw_lengths = [self.raw_lengths[i] for i in contigs_longer_than_M]
            self.run.info('contigs_raw_longer_than_M', len(self.references))


    def init_output_directory(self):
        Absolute = lambda x: os.path.join(os.getcwd(), x) if not x.startswith('/') else x

        if not self.output_directory:
            self.output_directory = Absolute(self.input_file_path) + '-PaPi-OUTPUT'
        else:
            self.output_directory = Absolute(self.output_directory)

        if not os.path.exists(self.output_directory):
            try:
                os.makedirs(self.output_directory)
            except:
                self.progress.end()
                raise utils.ConfigError, "Output directory does not exist (attempt to create one failed as well): '%s'" % \
                                                                (self.output_directory)
        if not os.access(self.output_directory, os.W_OK):
            self.progress.end()
            raise utils.ConfigError, "You do not have write permission for the output directory: '%s'" % self.output_directory


    def generate_output_destination(self, postfix, directory = False):
        return_path = os.path.join(self.output_directory, postfix)

        if directory == True:
            if os.path.exists(return_path):
                shutil.rmtree(return_path)
            os.makedirs(return_path)

        return return_path


    def profile(self):
        """Big deal function"""

        self.progress.new('Profiling the BAM file for Essential Stats')
        # So we start with essential stats. In the section below, we will simply go through each reference (contig),
        # in the BAM file and populate the references dictionary for the first time. There are two major sections,
        # one for no_threading option, and the other with multiple threads.
        if self.no_trehading:
            for i in range(0, len(self.references)):
                reference = self.references[i]
                self.references_dict[reference] = {}

                #fill in basics
                self.progress.update('Essential stats for "%s" (%d of %d) ...' % (reference, i + 1, len(self.references)))
                self.references_dict[reference]['essential'] = Essential(reference, self.bam.pileup(reference)).report()

        else:
            def worker(reference, shared_references_dict):
                shared_references_dict[reference] = Essential(reference, self.bam.pileup(reference)).report()

            mp = utils.Multiprocessing(worker, self.number_of_threads)
            shared_references_dict = mp.get_empty_shared_dict()

            # arrange processes
            processes_to_run = []
            for reference in self.references:
                processes_to_run.append((reference, shared_references_dict),)

            # start the main loop to run all processes
            mp.run_processes(processes_to_run, self.progress)
            for reference in self.references:
                self.references_dict[reference] = {}
                self.references_dict[reference]['essential'] = shared_references_dict.pop(reference)
        self.progress.end()


        # breath in, breath out. filtering based on M and C starts.
        self.progress.new('Filtering contigs based on min-length')
        # this is important:
        # paired-end libraries with large inserts can cover long areas with large empty areas in between. after
        # analyzing the coverage across each contig, we know the actual lenght of real nucleotides (this information
        # is held by ['essential']['length']). so we will further eliminate contigs that are kinda useless:
        self.progress.update('Screening actual contig lengths ...')
        references_to_discard = set()
        for reference in self.references_dict:
            if self.references_dict[reference]['essential']['length'] < self.min_contig_length:
                references_to_discard.add(reference)

        if len(references_to_discard):
            for reference in references_to_discard:
                self.references_dict.pop(reference)
            self.references = self.references_dict.keys()
            self.progress.end()
            self.run.info('contigs_precise_longer_than_M', pp(len(self.references)))
        else:
            self.progress.end()

        if not len(self.references):
            raise utils.ConfigError, "0 contigs passed minimum contig length parameter."

        self.progress.new('Filtering contigs based on mean coverage')
        # this is also important. here we are going to remove any contig with a mean coverage less than C; mean
        # coverage info is stored in ['essential']['mean_coverage']. the mean coverage does not include areas
        # where zero reads mapped. 
        self.progress.update('Screening coverage for each contig ...')
        references_to_discard = set()
        for reference in self.references_dict:
            if self.references_dict[reference]['essential']['mean_coverage'] < self.min_mean_coverage:
                references_to_discard.add(reference)

        if len(references_to_discard):
            for reference in references_to_discard:
                self.references_dict.pop(reference)
            self.references = self.references_dict.keys()
            self.progress.end()
            self.run.info('contigs_after_C', pp(len(self.references)))
        else:
            self.progress.end()

        if not len(self.references):
            raise utils.ConfigError, "0 contigs passed minimum mean coverage parameter."

        # QA/QC is done. Now we go into Auxiliary analyses.
        self.progress.new('Computing auxiliary stats')
        if self.no_trehading:
            for i in range(0, len(self.references)):
                reference = self.references[i]
                # fill in entropy and representatives
                self.progress.update('Auxiliary stats for "%s" (%d of %d) ...' % (reference, i + 1, len(self.references)))
                self.references_dict[reference]['auxiliary'] = Auxiliary(reference,
                                                                         self.bam.pileup(reference),
                                                                         self.references_dict[reference]['essential']\
                                                                         ).report()
        else:
            def worker(reference, shared_references_dict):
                shared_references_dict[reference] = Auxiliary(reference,
                                                              self.bam.pileup(reference),
                                                              self.references_dict[reference]['essential']\
                                                              ).report()

            mp = utils.Multiprocessing(worker, self.number_of_threads)
            shared_references_dict = mp.get_empty_shared_dict()

            # arrange processes
            processes_to_run = []
            for reference in self.references:
                processes_to_run.append((reference, shared_references_dict),)

            # start the main loop to run all processes
            mp.run_processes(processes_to_run, self.progress)
            for reference in self.references:
                self.references_dict[reference]['auxiliary'] = shared_references_dict.pop(reference)
        self.progress.end()


        # it is time to fill in the tetranucleotide frequency info per contig
        self.progress.new('TNF Stats')
        if self.no_trehading:
            for i in range(0, len(self.references)):
                reference = self.references[i]
                self.progress.update('Computing TNF for "%s" (%d of %d) ...' % (reference, i + 1, len(self.references)))
                self.references_dict[reference]['composition'] = Composition(reference,
                                                                             self.references_dict[reference]['auxiliary']\
                                                                             ).report()
        else:
            def worker(reference, shared_references_dict):
                shared_references_dict[reference] = Composition(reference,
                                                                self.references_dict[reference]['auxiliary']\
                                                                ).report()

            mp = utils.Multiprocessing(worker, self.number_of_threads)
            shared_references_dict = mp.get_empty_shared_dict()

            # arrange processes
            processes_to_run = []
            for reference in self.references:
                processes_to_run.append((reference, shared_references_dict),)

            # start the main loop to run all processes
            mp.run_processes(processes_to_run, self.progress)
            for reference in self.references:
                self.references_dict[reference]['composition'] = shared_references_dict.pop(reference)
        self.progress.end()

        # Profiling is done.


    def store_profile(self):
        output_file = self.generate_output_destination('PROFILE.cPickle')
        self.progress.new('Storing Profile')
        self.progress.update('Serializing information for %s contigs ...' % pp(len(self.references_dict)))
        cPickle.dump(self.references_dict, open(output_file, 'w'))
        self.progress.end()
        self.run.info('profile_dict', output_file)


    def load_profile(self):
        pass


    def report(self):
        # generate a sorted list of references based on length
        self.references = [t[1] for t in sorted([(self.references_dict[k]['essential']['length'], k)\
                                                for k in self.references], reverse = True)]

        self.progress.new('Generating reports')
        self.progress.update('TNF matrix for contigs')
        TNF_matrix_file_path = self.generate_output_destination('TETRANUCLEOTIDE-FREQ-MATRIX.txt')
        output = open(TNF_matrix_file_path, 'w')
        kmers = sorted(self.references_dict[self.references[0]]['composition']['tnf'].keys())
        output.write('contigs\t%s\n' % ('\t'.join(kmers)))
        for reference in self.references:
            output.write('%s\t' % (reference))
            output.write('%s\n' % '\t'.join([str(self.references_dict[reference]['composition']['tnf'][kmer]) for kmer in kmers]))
        output.close()
        self.progress.end()
        self.run.info('tnf_matrix', TNF_matrix_file_path)


        self.progress.new('Generating reports')
        self.progress.update('Generating the tree of contigs')
        newick_tree_file_path = self.generate_output_destination('TNF-NEWICK-TREE.txt')
        env = os.environ.copy()
        subprocess.call(['papi-TNF-matrix-to-newick.R', '-o', newick_tree_file_path, TNF_matrix_file_path], env = env)
        self.progress.end()
        self.run.info('tnf_tree', newick_tree_file_path)


        # metadata
        self.progress.new('Generating reports')
        self.progress.update('Metadata for contigs')
        metadata_fields = [('essential', 'length'), ('essential', 'mean_coverage'), ('essential', 'std_coverage'), 
                           ('composition', 'GC_content')]

        metadata_txt = open(self.generate_output_destination('METADATA.txt'), 'w')
        metadata_json = open(self.generate_output_destination('METADATA.json'), 'w')
        metadata_json_buffer = []

        fields = [m[1] for m in metadata_fields]
        metadata_txt.write('contigs\t%s\n' % ('\t'.join(fields)))
        metadata_json_buffer.append([''] + fields)

        for reference in self.references:
            l = [self.references_dict[reference][major][minor] for major, minor in metadata_fields]
            fields = [reference] + ['%.4f' % x for x in l]
            metadata_txt.write('%s\n' % '\t'.join(fields))
            metadata_json_buffer.append(fields)

        metadata_txt.close()
        metadata_json.write(json.dumps(metadata_json_buffer))
        metadata_json.close()
        self.progress.end()
        self.run.info('metadata_txt', metadata_txt.name)
        self.run.info('metadata_json', metadata_json.name)



    def check_args(self):
        if (not self.input_file_path) and (not self.serialized_profile_path):
            raise utils.ConfigError, "You must declare either an input file, or a serialized profile."
        if self.input_file_path and self.serialized_profile_path:
            raise utils.ConfigError, "You can't declare both an input file and a serialized profile."
        if self.serialized_profile_path and (not self.output_directory):
            raise utils.ConfigError, "When loading serialized profiles, you need to declare an output directory."
        if self.input_file_path and not os.path.exists(self.input_file_path):
            raise utils.ConfigError, "No such file: '%s'" % self.input_file_path
        if self.serialized_profile_path and not os.path.exists(self.serialized_profile_path):
            raise utils.ConfigError, "No such file: '%s'" % self.serialized_profile_path
        if not self.min_mean_coverage > 0:
            raise utils.ConfigError, "Minimum mean coverage must be 1 or larger"
        if not self.min_contig_length > 0:
            raise utils.ConfigError, "Minimum contig length must be 1 or larger (although using anything below 5,000 is kinda silly)."