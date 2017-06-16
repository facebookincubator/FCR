#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import argparse

from argparse import HelpFormatter
from operator import attrgetter


class SortingHelpFormatter(HelpFormatter):

    def add_arguments(self, actions):
        actions = sorted(actions, key=attrgetter('option_strings'))
        super(SortingHelpFormatter, self).add_arguments(actions)


class Option:
    '''
    A simple wrapper around argparse.
    '''

    config = None
    parser = argparse.ArgumentParser(formatter_class=SortingHelpFormatter)

    def __init__(self, *args, **kwargs):
        self._action = Option.parser.add_argument(*args, **kwargs)
        self._dest = self._action.dest

    @classmethod
    def parse_args(cls, args=None):
        Option.config = Option.parser.parse_args(args)

    def __get__(self, instance, owner):
        return getattr(Option.config, self._dest)

    def __set__(self, instance, value):
        '''Options are immutable and can't be set'''
        raise AttributeError()
