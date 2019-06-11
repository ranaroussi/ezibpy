#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# ezIBpy: a Pythonic Client for Interactive Brokers API
# https://github.com/ranaroussi/ezibpy

"""ezIBpy: a Pythonic Client for Interactive Brokers API
ezIBpy is a Pythonic wrapper for IbPy library
(https://github.com/blampe/IbPy), that was developed to
speed up the development of trading software that relies on
Interactive Brokers for market data and order execution.
"""

from setuptools import setup, find_packages
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='ezIBpy',
    version="1.12.69",
    description='a Pythonic Client for Interactive Brokers API',
    long_description=long_description,
    url='https://github.com/ranaroussi/ezibpy',
    author='Ran Aroussi',
    author_email='ran@aroussi.com',
    license='Apache Software License',
    classifiers=[
        'License :: OSI Approved :: Apache Software License',
        'Development Status :: 5 - Production/Stable',

        'Operating System :: OS Independent',
        'Intended Audience :: Developers',
        'Topic :: Office/Business :: Financial',
        'Topic :: Office/Business :: Financial :: Investment',
        'Topic :: Scientific/Engineering :: Interface Engine/Protocol Translator',
        'Topic :: Software Development :: Libraries',
        'Topic :: Software Development :: Libraries :: Python Modules',

        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
    ],
    platforms = ['any'],
    keywords='ezibpy, interactive brokers, tws, ibgw, ibpy',
    packages=find_packages(exclude=['contrib', 'docs', 'tests', 'examples']),
    install_requires=['pandas>=0.23.0', 'python-dateutil>=2.5.3', 'ibpy2>=0.8.0'],
    entry_points={
        'console_scripts': [
            'sample=sample:main',
        ],
    },
)
