"""Local contract validation; never resolve schemas over the network."""

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.exceptions import NoSuchResource


def no_remote_schema(uri):
    raise NoSuchResource(ref=uri)


def contract_errors(schema, value):
    Draft202012Validator.check_schema(schema or {})
    return list(Draft202012Validator(schema or {}, registry=Registry(retrieve=no_remote_schema)).iter_errors(value))
