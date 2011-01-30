import os
from setuptools import setup, find_packages

VERSION = '0.1'

setup(name='plugwiselib', 
    version=VERSION,
    description='A library for communicating with Plugwise smartplugs',
    author='Sven Petai',
    author_email='hadara@bsd.ee',
    license='MIT',
    packages=find_packages(),
    py_modules=['plugwise'],
    install_requires=['crcmod', 'pyserial'],
    scripts=['plugwise_util'],
)

