from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

import abc
import builtins
import datetime
import enum
import typing

import jsii
import publication
import typing_extensions

from jsii._type_checking import check_type


__jsii_assembly__ = jsii.JSIIAssembly.load(
    "@aws-cdk/cloud-assembly-schema",
    "54.3.0",
    __name__[0:-6],
    "cloud-assembly-schema@54.3.0.jsii.tgz",
)

__all__ = [
    "__jsii_assembly__",
]

publication.publish()
