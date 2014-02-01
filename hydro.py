""" The Hydro Framework """

__author__ = "James Dalessio <dalessio.james@gmail.com>"

import os
import traceback
import copy
import collections
import webapp2
import json
import xml.etree.ElementTree


class _HTTPException(Exception):
    """Exception with a message and HTTP status code.

    Raise an instance of this class (or the class itself) with an
    appropriate HTTP status code when an error state is reached.

    See RFC2616 for a list of established HTTP status codes.

    Attributes:
        code: An integer corresponding to the HTTP status code that
            best describes the error.
        message: A short string describing the error.

    Class Attributes:
        message_map: A dictionary that maps status codes to messages.
            When a message is not specified and an entry in this
            dictionary exists for the given status code, the message
            will be obtained from this dictionary.
    """

    code = 500
    message = "An unknown error has occured."

    message_map = {
        403: "Unauthorized",
        404: "Resource Not Found",
        499: "Unknown client error."
    }

    def __init__(self, code=None, message=None, **kwargs):
        if code is not None:
            self.code = code
        if message is not None:
            self.message = message
        elif self.code in self.message_map:
            self.message = self.message_map[self.code]
        for key, val in kwargs.iteritems():
            setattr(self, key, val)


class _Localized(object):
    def __init__(self, id):
        self.id = id


class _Field(object):

    _counter = 0

    def __init__(self, default=None, alias=None, simple_alias=None):
        self._default = default
        self._alias = alias
        self._index = self._counter
        self._simple_alias = simple_alias
        _Field._counter += 1

    def __get__(self, parent, _=None):
        if parent is None:
            return self
        if self._name in parent.__dict__:
            value = parent.__dict__[self._name]
        else:
            value = copy.deepcopy(self._default)
            setattr(parent, self._name, value)
        return value


class _Input(_Field):
    
    def __init__(self, default=None, optional=False,
                 multivalued=False, **kwargs):
        self._optional = optional
        self._multivalued = multivalued
        super(_Input, self).__init__(default=default, **kwargs)

    def _coerce(self, value):
        return value
        
                 
class _Output(_Field):
    
    def __init__(self,
                 default=None,
                 alias=None,
                 simple_alias=None,
                 multivalued=False,
                 **kwargs):
        super(_Output, self).__init__(
            default=default,
            alias=alias,
            simple_alias=simple_alias)
        self._multivalued = multivalued
        self._meta = {}
        self._meta.update(kwargs)


class _Meta(_Field):
    def __init__(self, value, **kwargs):
        super(_Meta, self).__init__(value, **kwargs)


class _Inherited(object):

    def __init__(self, *names):
        self._names = names

    def _resolve(self, field, entity):
        if not self._names:
            return getattr(entity, field._name)
        for name in self.names:
            entity = getattr(entity, name)
        return entity


class _String(_Input):
    
    def _coerce(self, value):
        if isinstance(value, basestring):
            return value
        return str(value)

        
class _SafeString(_Input):

    def _coerce(self, value):
        import bleach
        value = unicode(value)
        value = "".join(c for c in value if ord(c) > 31)
        return bleach.clean(value, strip=True)


class _Boolean(_Input):
    """A field whose value is True or False."""

    _falses = [False, 0, 'False', 'false', 'No', 'no', 'NO' ]

    def _coerce(self, value):
        return value not in self._falses


class _Float(_Input):
    """View field whose value is a float."""

    def _coerce(self, value):
        return float(value)


class _Integer(_Input):
    """A Model field whose value is an integer."""

    def _coerce(self, value):
        return long(value)


class _MetaView(type):

    def __init__(cls, name, bases, cdict):

        super(_MetaView, cls).__init__(name, bases, cdict)

        path = cdict.get('path')
        method = cdict.get('method')
        if path is None:
            for base in bases:
                if hasattr(base, 'path'):
                    path = base.path
                    break
        if method is None:
            for base in bases:
                if hasattr(base, 'method'):
                    method = base.method
                    break
        if path is not None:
            if not method in cls._mapping:
                cls._mapping[method] = {}
            cls._mapping[method][path] = cls

        cls._inputs = collections.OrderedDict()
        cls._outputs = collections.OrderedDict()
        cls._metas = collections.OrderedDict()
        for cls_ in bases:
            cls._inputs.update(
                getattr(cls_, '_inputs', collections.OrderedDict()))
            cls._outputs.update(
                getattr(cls_, '_outputs', collections.OrderedDict()))
            cls._metas.update(
                getattr(cls_, '_metas', collections.OrderedDict()))

        inputs = []
        outputs = []
        metas = []
        for name_ in set(dir(cls)):
            value = getattr(cls, name_)
            if not isinstance(value, _Field):
                continue
            value._name = name_
            if isinstance(value, _Input):
                inputs.append(value)
            elif isinstance(value, _Output):
                outputs.append(value)
            elif isinstance(value, _Meta):
                metas.append(value)

        inputs = sorted(inputs, key=lambda x: x._index)
        outputs = sorted(outputs, key=lambda x: x._index)
        metas = sorted(metas, key=lambda x: x._index)

        for input in inputs:
            cls._inputs[input._name] = input
        for output in outputs:
            cls._outputs[output._name] = output
        for meta in metas:
            cls._metas[meta._name] = meta


class _View(object):

    __metaclass__ = _MetaView

    method = 'GET'
    _mapping = {}

    def __init__(self, entity=None):
        self._entity = entity


    @property
    def headers(self):
        return self._webapp2_response.headers

    def to_dict(self):
        d = {'name': 'resource', 'meta': {}, 'value': None, 'contents': []}
        if hasattr(self, 'name'):
            d['name'] = str(self.name)
        elif hasattr(self, 'path'):
            d['name'] = str(self.path)

        for name, meta in self._metas.iteritems():
            meta_value = getattr(self, name)
            if isinstance(meta_value, _Inherited):
                meta_value = meta_value._resolve(meta, self.entity)
            d['meta'][meta._alias or meta._name] = meta_value
        
        for name, output in self._outputs.iteritems():
            value = getattr(self, name)
            if isinstance(value, _Inherited):
                value = value._resolve(output, self.entity)
            if output._multivalued and value is not None:
                for value_ in value:
                    if isinstance(value_, _View):
                        f = value_.to_dict()
                        f['name'] = output._alias or name
                        f['meta'].update(output._meta)
                    else:
                        f = {'name': output._alias or name, 'meta': {},
                             'value': value_, 'contents': []}
                    f['meta'].update(output._meta)
                    d['contents'].append(f)
                continue
            if isinstance(value, _View):
                f = value.to_dict()
                f['name'] = output._alias or name
                f['meta'].update(output._meta)
                d['contents'].append(f)
                continue

            f = {'name': output._alias or name, 'meta': {},
                 'value': value, 'contents': []}
            f['meta'].update(output._meta)
            d['contents'].append(f)
        return d

    def to_simple_dict(self):
        d = {}
        for name, output in self._outputs.iteritems():
            value = getattr(self, name)
            alias = output._simple_alias or output._alias or name
            if isinstance(value, _Inherited):
                value = value._resolve(output, self.entity)
            if output._multivalued and value is not None:
                f = []
                for value_ in value:                    
                    if isinstance(value_, _View):
                        f.append(value_.to_simple_json_dict())
                    else:
                        f.append(value_)
                d[alias] = f
                continue
            if isinstance(value, _View):
                d[alias] = value.to_simple_json_dict()
                continue
            d[alias] = value
        return d

    def pre_response_hook(self):
        pass

    def post_response_hook(self):
        pass

    def response(self):
        pass

    @property
    def address(self):
        return webapp2.get_request().remote_addr

    def redirect(self, url):
        webapp2.redirect(url, abort=True)

    def abort(self, *args, **kwargs):
        raise _HTTPException(*args, **kwargs)


class _Encoder(object):

    def __init__(self, content_type=None):
        if content_type is not None:
            self.content_type = content_type

    def encode(self, view):
        return str()

    def encode_error(self, exception):
        return str()

    content_type = ''


class _FieldEncoder(_Encoder):

    def __init__(self, fieldname, **kwargs):
        self.fieldname = fieldname
        super(_FieldEncoder, self).__init__(**kwargs)

    def encode(self, view):
        return getattr(view, self.fieldname)


class _FileEncoder(_Encoder):

    def __init__(self, filename=None, **kwargs):
        self.filename = filename
        super(_FileEncoder, self).__init__(**kwargs)
    
    def encode(self, view):
        file = open(self.filename or view.filename, 'r')
        data = file.read()
        file.close()
        return data


class _XMLEncoder(_Encoder):

    def encode(self, view):
        root = self.encode_helper(None, view.to_dict())
        return xml.etree.ElementTree.tostring(root)

    def encode_helper(self, root, d):

        if root is None:
            e = xml.etree.ElementTree.Element(d['name'], **d['meta'])
        else:
            e = xml.etree.ElementTree.SubElement(root, d['name'], **d['meta'])

        value = d['value']
        contents = d['contents']
        if value is None:
            if contents:
                for v in contents:
                    self.encode_helper(e, v)
            else:
                e.text = " "
        else:
            e.text = unicode(value)
        return e

    def encode_error(self, e):
        main = xml.etree.ElementTree.Element("error")
        sub = xml.etree.ElementTree.SubElement(main, "message")
        sub.text = str(e.message)
        sub = xml.etree.ElementTree.SubElement(main, "code")
        sub.text = str(e.code)
        return xml.etree.ElementTree.tostring(main)

    content_type = 'application/xml'


class _JSONEncoder(_Encoder):

    def encode(self, view):
        return json.dumps(view.to_dict())

    def encode_error(self, e):
        return json.dumps({'message': e.message, 'code': e.code})

    content_type = 'application/json'


class _SimpleJSONEncoder(_Encoder):

    def encode(self, view):
        return json.dumps(view.to_simple_dict())

    def encode_error(self, e):
        return json.dumps({'message': e.message, 'code': e.code})

    content_type = 'application/json'


class _HTMLEncoder(_Encoder):

    def encode(self, view):
        return self._get_jinja().get_template(
            view.template).render(view.to_dict())
        
    def encode_error(self, exception):
        return "<h1>" + str(exception.code) + ":" + exception.message + "</h1>"

    def _get_jinja(self):
        import jinja2
        if not self._j2e:
            self._j2e = jinja2.Environment(
                loader=jinja2.FileSystemLoader(self._template_path),
                extensions=['jinja2.ext.autoescape'])
        return self._j2e

    _j2e = None

    _template_path = os.path.dirname(__file__)
    content_type = 'text/html'


class _Handler(webapp2.RequestHandler):
    """Base-class for request handlers."""

    encoders = [_XMLEncoder(), _HTMLEncoder(), _JSONEncoder()]

    def dispatch(self, **kwargs):
        
        self.select_encoder()
        try:
            self.create_view(**self.request.route_kwargs)
            self.modify_view()
            self.view.pre_response_hook()
            self.view.response()
            self.view.post_response_hook()
            self.response.write(self.encoder.encode(self.view))
        except _HTTPException as e:
            self.handle_error(e)
        return self.response

    def select_encoder(self):
        accept = self.request.headers.get('Accept')
        if self.request.get('format'):
            accept = self.request.get('format')
        for encoder in reversed(self.encoders):
            self.encoder = encoder
            if encoder.content_type in accept:
                break
        self.response.headers['Content-Type'] = encoder.content_type

    def create_view(self, view_name=None, entity_name=None):
        if not view_name:
            if self.request.path == '/':
                view_name = "/"
            else:
                raise _HTTPException(404)

        view_class = _View._mapping.get(self.request.method, {}).get(view_name)
        if view_class is None:
            raise _HTTPException(404)
        self.view = view_class()
        accept = self.request.headers.get('Accept')
        if self.request.get('format'):
            accept = self.request.get('format')
        for encoder in reversed(self.view.encoders):
            self.encoder = encoder
            if encoder.content_type in accept:
                break
        self.response.headers['Content-Type'] = encoder.content_type
        self.view.entity_name = entity_name
        self.view._webapp2_request = self.request
        self.view._webapp2_response = self.response

    def modify_view(self):
        modifications = {}
        for key, value in self.request.params.iteritems():
            if key not in modifications:
                modifications[key] = []
            modifications[key].append(value)
        for name, input in self.view._inputs.iteritems():
            if input._multivalued and input._default is None:
                setattr(self.view, name, [])
            if not (input._alias or name) in modifications:
                continue
            try:
                value = [input._coerce(v) for v in modifications[
                    input._alias or name]]
            except (TypeError, ValueError):
                continue
            if not input._multivalued:
                value = value[-1]
            setattr(self.view, name, value)
        for name, input in self.view._inputs.iteritems():
            if input._optional or input._default is not None:
                continue
            if getattr(self.view, name) is None:
                message = "No %s specified" % (input._alias or name)
                raise _HTTPException(
                    400, message)

    def handle_error(self, exception):
        traceback.print_exc()
        if isinstance(exception, _HTTPException):
            self.response.set_status(exception.code, exception.message)
            self.response.out.write(
                self.encoder.encode_error(exception))
        else:
            raise exception


class Hydro(webapp2.WSGIApplication):
    """The application."""

    def __init__(self, template_path=None, default_template=None, **kwargs):

        if template_path is not None:
            _HTMLEncoder._template_path = template_path

        if default_template is not None:
            _View.template = default_template

        super(Hydro, self).__init__(
            [
                webapp2.Route('/', _Handler),
                webapp2.Route('/<view_name>', _Handler),
                webapp2.Route('/<view_name>/', _Handler),
                webapp2.Route('/<view_name>/<entity_name>', _Handler),
                webapp2.Route('<:.*>', _Handler),
            ],
            config=kwargs,
        )


Handler = _View

Input = _Input
String = _String
Integer = _Integer
Float = _Float
Boolean = _Boolean

Meta = _Meta

Output = _Output
Inherited = _Inherited

Encoder = _Encoder
FieldEncoder = _FieldEncoder
FileEncoder = _FileEncoder
XMLEncoder = _XMLEncoder
HTMLEncoder = _HTMLEncoder
JSONEncoder = _JSONEncoder
SimpleJSONEncoder = _SimpleJSONEncoder
