"""The Hydro Appengine Framework

The docstrings here are intended to serve as little bits of help for
developers, not as documentation of the public API. Please see the
associated README for information about how to *USE* Hydro.

"""

__version__ = 0.0

import os
import traceback
import copy
import uuid
import collections
import inspect
import datetime

import webapp2
import bleach  # Not included in GAE

from xml.etree.ElementTree import SubElement, tostring
from xml.etree.ElementTree import Element as Element_
from base64 import urlsafe_b64encode

from google.appengine.ext import ndb as _ndb
from google.appengine.datastore.datastore_query import Cursor as _GAECursor
from google.appengine.api.datastore_errors import BadValueError\
    as _GAEBadValueError
from google.appengine.ext import blobstore
from google.appengine.api import images
from google.appengine.ext.appstats import recording
from google.appengine.api import mail as _mail


_DEVELOPMENT = os.environ.get('SERVER_SOFTWARE', 'Dev').startswith('Dev')
_BOOLEAN_FALSES = [False, 0, 'False', 'false', 'No', 'no', 'NO' ]

get_request = webapp2.get_request


def generate_opaque_id():
    return urlsafe_b64encode(uuid.uuid4().bytes)[0:22]





def abort(*args, **kwargs):
    raise _HTTPException(*args, **kwargs)


def get_current_address():
    return webapp2.get_request().remote_addr

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

    """Data container for Models and Views.

    Note that fields are attached to a model or view by the model/view
    metaclass; see "_PseudoField".

    """

    _tag = None
    _multivalued = False
    _indexed = False
    _indexable = False
    _modifiable = False
    _pass_name = False
    _fixed_metadata = None
    _required = True

    _name = None
    _parent_class = None

    _counter = 0

    def __init__(self,
                 default=None,
                 tag=None,
                 multivalued=None,
                 indexed=None,
                 metadata=None,
                 required=None,
                 **kwargs):
        self._default_ = default
        if tag is not None:
            self._tag = tag
        if multivalued is not None:
            self._multivalued = multivalued
        if indexed is not None:
            self._indexed = indexed
        if not self._indexable:
            self._indexed = False
        self._metadata = {}
        if metadata is not None:
            self._metadata.update(metadata)
        self._metadata.update(kwargs)
        if self._fixed_metadata is not None:
            self._metadata.update(self._fixed_metadata)
        if required is not None:
            self._required = required
        self._index = self._counter
        _Field._counter += 1

    def __get__(self, parent, _=None):
        if parent is None:
            return self
        if self._name in parent.__dict__:
            value = parent.__dict__[self._name]
        else:
            value = copy.deepcopy(self._default_)
            setattr(parent, self._name, value)
        if self._multivalued:
            if value is None:
                return []
            if not isinstance(value, (list, tuple)):
                return [value]
        return value

class _Output(_Field):
    pass

class _Inherited(_Field):
    def __init__(self, *args):
        self.names = args
        super(_Inherited, self).__init__()

    def get_value(self, entity):
        if not self.names:
            return getattr(entity, self._name)

        for name in self.names:
                
            if isinstance(entity, dict):
                entity = entity[name]
            else:
                if name == '__id__':
                    entity = entity.key.id()
                else:
                    entity = getattr(entity, name)
        return entity


class _Static(_Field):
    """Field with a fixed value."""

    def __get__(self, parent, _=None):
        if parent is None:
            return self
        return self._default_


class _Meta(_Static):
    pass


class _Computed(_Field):
    """Field with a value computed by the Model/View."""

    def __get__(self, parent, _=None):
        if parent is None:
            return self
        return getattr(parent, self._default_)()


class _StandardField(_Field):

    _indexable = True
    _modifiable = True
    _ndb_class = None

    def __init__(self, *args, **kwargs):
        _Field.__init__(self, *args, **kwargs)
        self._ndb_class.__init__(
            self,
            indexed=self._indexed,
            repeated=self._multivalued,
        )

    def _coerce(self, value):
        return value

    def _coerce_filter_value(self, value):
        return self._coerce(value)

    def __set__(self, parent, value):
        if isinstance(parent, _ndb.Model):
            self._ndb_class.__set__(self, parent, value)
        else:
            parent.__dict__[self._name] = value

    def __get__(self, parent, _=None):
        if parent is None:
            return self
        elif isinstance(self, _ndb.Property) and isinstance(parent, _ndb.Model):
            value = self._get_value(parent)
            if value is None:
                return super(_StandardField, self).__get__(parent, _)
            return value
        else:
            return super(_StandardField, self).__get__(parent, _)


_Input = _StandardField


class _BlobInput(_StandardField):

    def _coerce(self, value):
        return blobstore.parse_blob_info(value)


class _String(_StandardField, _ndb.StringProperty):
    """View field whose value is a string."""

    _ndb_class = _ndb.StringProperty

    def __init__(self, *args, **kwargs):
        self._STRIP_ = kwargs.get('_STRIP_', True)
        _StandardField.__init__(self, *args, **kwargs)

    def _coerce(self, value):
        value = unicode(value)
        value = "".join(c for c in value if ord(c) > 31)
        if self._STRIP_:
            return bleach.clean(value, strip=True)
        return value

    def _coerce_filter_value(self, value):
        return str(value)

_StringInput = _String

class _Boolean(_StandardField, _ndb.BooleanProperty):
    """A field whose value is True or False."""

    _ndb_class = _ndb.BooleanProperty

    def _coerce(self, value):
        return value not in _BOOLEAN_FALSES

_BooleanInput = _Boolean

class _Float(_StandardField, _ndb.FloatProperty):
    """View field whose value is a float."""

    _ndb_class = _ndb.FloatProperty

    def _coerce(self, value):
        return float(value)

_FloatInput = _Float

class _Integer(_StandardField, _ndb.IntegerProperty):
    """A Model field whose value is an integer."""

    _ndb_class = _ndb.IntegerProperty

    def _coerce(self, value):
        return long(value)

_IntegerInput = _Integer



class _Serial(_StandardField, _ndb.JsonProperty):
    
    _ndb_class = _ndb.JsonProperty


class _NestedModel(_ndb.StructuredProperty, _Field):

    def __init__(self, model, **kwargs):
        self._model = model
        _Field.__init__(self, **kwargs)
        _ndb.StructuredProperty.__init__(self, model, **kwargs)


class _SerialNestedModel(_ndb.LocalStructuredProperty, _Field):

#    def validate(*args, **kwargs):
#        return 

    def __init__(self, model, multivalued=False, **kwargs):
        self._model = model
        _Field.__init__(self, multivalued=multivalued, **kwargs)
        _ndb.LocalStructuredProperty.__init__(
            self, model, repeated=multivalued, **kwargs)


class _NestedView(_Field):

    def __init__(self, view, **kwargs):
        self._view = view
        super(_NestedView, self).__init__(**kwargs)


class _Filter(_Field):
    """Transient property whose value is a filter for queries."""

    def __init__(self, field, default=None, operator=None,
                 ignore_unset=True, modifiable=True, **kwargs):
        super(_Filter, self).__init__(default, **kwargs)
        self._field = field
        if operator == '<':
            self._operator = '__lt__'
        elif operator == '<=':
            self._operator = '__le__'
        elif operator == '>':
            self._operator = '__gt__'
        elif operator == '>=':
            self._operator = '__ge__'
        else:
            self._operator = '__eq__'
        self._ignore_unset = ignore_unset
        self._modifiable = modifiable

    def _coerce(self, value):
        try:
            return self._field._coerce_filter_value(value)
        except (TypeError, AttributeError):
            pass


class _Page(_Field):
    """Field whose value is a GAE cursor."""
    def _coerce(self, value):
        try:
            return _GAECursor(urlsafe=value)
        except _GAEBadValueError:
            raise ValueError


class _MetaBase(type):

    def __init__(cls, name, bases, cdict):

        super(_MetaBase, cls).__init__(name, bases, cdict)
        cls._fields = collections.OrderedDict()
        for cls_ in bases:
            cls._fields.update(
                getattr(cls_, '_fields', collections.OrderedDict()))

        fl = []
        for name_ in set(dir(cls)):
            value = getattr(cls, name_)
            if isinstance(value, _Field):
                value._name = name_
                value._parent_class = cls
                fl.append(value)

        fl = sorted(fl, key=lambda x: x._index)
        for field in fl:
            cls._fields[field._name] = field


class _MetaView(_MetaBase):
    def __init__(cls, name, bases, cdict):
        path = cdict.get('path')
        if path:
            cls._mapping[path.lower()] = cls
        super(_MetaView, cls).__init__(name, bases, cdict)


class _ViewAndModelBase(object):

    _as_dictionary = None

    def _internal_dictionary_hook(self):
        pass

    @property
    def as_dictionary(self):
        if self._as_dictionary is not None:
            return self._as_dictionary
        self._as_dictionary = dict()
        if getattr(self, 'tag', None):
            self._as_dictionary['tag'] = self.tag
        elif self.path:
            self._as_dictionary['tag'] = self.path
        else:
            self._as_dictionary['tag'] = self.__class__.__name__.lower()
        if self._as_dictionary['tag'] == '/':
            self._as_dictionary['tag'] = 'front_page'
        self._as_dictionary['value'] = str()
        self._as_dictionary['contents'] = []
        self._as_dictionary['metadata'] = {}
        for name, field in self._fields.iteritems():
            if isinstance(field, _Meta):
                self._as_dictionary['metadata'][name] = getattr(self, name)
                continue
            if not isinstance(field, _Output):
                continue
            d = dict()
            d['tag'] = field._tag if field._tag else field._name
            d['value'] = getattr(self, name)
            d['contents'] = []
            d['metadata'] = {}
            d['metadata'].update(field._metadata)
            for key in d['metadata']:
                if isinstance(d['metadata'][key], _Inherited):
                    d['metadata'][key] = d['metadata'][key].get_value(
                        self.entity)
                if isinstance(d['metadata'][key], _Localized):
                    pass
            if field._pass_name:
                d['metadata']['name'] = field._name
            if isinstance(d['value'], (_View, _ndb.Model)):
                r = d['value'].as_dictionary
                d['value'] = str()
                d['contents'] = r['contents']
                d['metadata'].update(r['metadata'])
            if isinstance(field, _Inherited):
                print 'INHERITED'
                d['value'] = field.get_value(self.entity)
            self._as_dictionary['contents'].append(d)
        for key in self._as_dictionary['metadata']:
            if isinstance(self._as_dictionary['metadata'][key], _Inherited):
                d['metadata'][key].get_value(self.entity)
        self._internal_dictionary_hook()
        return self._as_dictionary

    @staticmethod
    def create_blobstore_upload_url(path):
        return blobstore.create_upload_url(path)

    @staticmethod
    def create_blobstore_image_url(blobinfo, **kwargs):
        return images.get_serving_url(blobinfo, **kwargs)

    @property
    def remote_address(self):
        return webapp2.get_request().remote_addr

    @property
    def address(self):
        return webapp2.get_request().remote_addr


class _ViewBase(_ViewAndModelBase):

    _mapping = {}
    path = None
    template = "index.html"

    def dispatch(self):
        self.handler()
        self.respond()

    def handler(self):
        pass

    def respond(self):
        pass

    def redirect(self, view_or_string, resource=None):
        if isinstance(view_or_string, basestring):
            webapp2.redirect(view_or_string, abort=True)
        url = '/' + view_or_string.path
        if resource:
            url = url + '/' + resource.id
        webapp2.redirect(url, abort=True)


class _View(_ViewBase):

    __metaclass__ = _MetaView

    path = None
    model = None
    key = None
    _entity = None
    id = None

    def __init__(self, entity=None):
        self._entity = entity

    def abort(self, *args, **kwargs):
        abort(*args, **kwargs)

    @property
    def address(self):
        return webapp2.get_request().remote_addr

    @property
    def now(self):
        return datetime.datetime.utcnow()

    @property
    def resource(self):
        return self.entity

    @resource.setter
    def resource(self, value):
        self.entity = value

    @property
    def entity(self):
        if self._entity is None:
            if self.key is None:
                raise HTTPException(404)
            self._entity = self.key.get()
            if self._entity is None:
                raise HTTPException(404)
        return self._entity

    @entity.setter
    def entity(self, value):
        self._entity = value

    @property
    def as_dictionary(self):
        if self._as_dictionary is not None:
            return self._as_dictionary
        d = super(_View, self).as_dictionary
        if self.key:
            d['metadata']['id'] = self.key.id()
        return d


class _GET(_View):
    _mapping = dict()


class _POST(_View):
    _mapping = dict()


class _Collection(_ViewBase):

    __metaclass__ = _MetaView

    view = None
    model = None

    def _internal_read_hook(self):
        pass

    def _internal_pre_modify_hook(self):
        pass

    def _internal_post_modify_hook(self):
        self.on_read()

    def invalidate_cache(self):
        # destroy first page in memcache to force new query results
        # needs something to generate the query without executing it
        pass

    @property
    def results(self):
        if self._results is None:
            self._execute_query()
        return self._results

    _results = None
    _next_page = None

    directions = []
    page = _Page()
    results_per_page = 10

    @property
    def as_dictionary(self):
        if self._as_dictionary is not None:
            return self._as_dictionary
        d = super(_Collection, self).as_dictionary
        d['tag'] = 'collection'
        d['contents'] = []
        for view in self.results:
            d['contents'].append(view.as_dictionary)
        self._internal_dictionary_hook()
        return self._as_dictionary

    def _execute_query(self):
        self._results = []
        if not self.view or not self.view.model:
            return
        query = self.view.model.query()
        for name, field in self._fields.iteritems():
            if isinstance(field, _Filter):
                value = getattr(self, name)
                if value is not None or not field._ignore_unset:
                    model_field = field._field
                    try:
                        value = model_field._coerce_filter_value(value)
                    except (TypeError, ValueError):
                        value = None
                    operator = getattr(model_field, field._operator)(value)
                    query = query.filter(operator)
        print query
        directions = self.directions
        if not (isinstance(directions, list) or isinstance(directions,
                                                           tuple)):
            directions = [directions]
        for direction in directions:
            if direction:
                query = query.order(direction)
        print query
        resources, next_cursor, _ = query.fetch_page(
            self.results_per_page,
            start_cursor=self.page)
        print resources
        views = []
        for resource in resources:
            resource.on_read()
            for name, field in resource._fields.iteritems():
                if isinstance(field, (_NestedModel, _SerialNestedModel)):
                    if not field._multivalued:
                        setattr(resource, name, field._model.create())
            if resource._use_instance_cache:
                self._instance_cache[resource.key.urlsafe()] = resource
            resource.put(use_memcache=False, use_datastore=False)
            views.append(self.view(resource=resource))
        for view in views:
            view.on_read()

        self._results = views
        if next_cursor:
            self._next_page = next_cursor.urlsafe()





HTTPException = _HTTPException


class _Encoder(object):
    @classmethod
    def encode(cls, resource):
        return str()

    @classmethod
    def make_exception_response(cls, e):
        return str()

    content_type = ''


class _XMLEncoder(_Encoder):

    @classmethod
    def encode(cls, resource):
        root = cls.encode_dict(None, resource.as_dictionary)
        return tostring(root)

    @staticmethod
    def remove_bad_chars(s):
        return "".join(c for c in s if ord(c) > 31)

    @classmethod
    def encode_dict(cls, root, d):

        if isinstance(d.get('value'), list):            
            for x in d.get('value'):
                newd = {
                    'tag': d['tag'],
                    'contents': d['contents'],
                    'value': x,
                    'metadata': d['metadata']
                }
                cls.encode_dict(root, newd)
            return


        for k, v in d['metadata'].iteritems():
            d['metadata'][k] = cls.remove_bad_chars(unicode(v))

        if root is None:
            e = Element_(d['tag'], **d['metadata'])
        else:
            e = SubElement(root, d['tag'], **d['metadata'])

        if d.get('value') is not None:
            e.text = cls.remove_bad_chars(unicode(d.get('value')))
        if d.get('value') == "":
            e.text = " "

        

        for value in d.get('contents', []):
            cls.encode_dict(e, value)
        return e

    @classmethod
    def make_exception_response(cls, e):
        main = Element_("error")
        sub = SubElement(main, "message")
        sub.text = str(e.message)
        sub = SubElement(main, "code")
        sub.text = str(e.code)
        return tostring(main)

    content_type = 'application/xml'


class _HTMLEncoder(_Encoder):

    @classmethod
    def encode(cls, resource):
        return cls._get_jinja().get_template(resource.template).render({
            'resource': resource.as_dictionary,
        })

    @classmethod
    def make_exception_response(cls, exception):
        return "<h1>" + str(exception.code) + ":" + exception.message + "</h1>"

    @classmethod
    def _get_jinja(cls):
        import jinja2
        if not cls._j2e:
            cls._j2e = jinja2.Environment(
                loader=jinja2.FileSystemLoader(cls._template_path),
                extensions=['jinja2.ext.autoescape'])
        return cls._j2e

    _j2e = None

    _template_path = os.path.dirname(__file__)
    content_type = 'text/html'


class _Handler(webapp2.RequestHandler):
    """Base-class for request handlers."""

    def dispatch(self, **kwargs):
        self.select_encoder()
        self.request.response = self.response
        try:
            self.create_view(**self.request.route_kwargs)
            self.view.request = self.request
            self.view.response = self.response
            self.modify_view()
            self.view.dispatch()
            self.response.write(self.get_encoding())
            self.clean_up()
        except _HTTPException as e:
            self.handle_error(e)

    def select_encoder(self):
        content_type = self.request.headers.get('Accept')
        for encoder in reversed(self.encoders):
            self.encoder = encoder
            if self.request.get('format'):
                if encoder.content_type in self.request.get('format'):
                    break
            elif content_type is None or encoder.content_type in content_type:
                break

        if not self.encoder:
            self.encoder = self.encoders[0]
        self.response.headers['Content-Type'] = encoder.content_type

    def create_view(self, view_name=None, resource_id=None):
        if not view_name:
            if self.request.path == '/':
                view_name = "/"
            else:
                raise _HTTPException(404)
        if self.request.method == 'GET':
            view_class = _GET._mapping.get(view_name)
        elif self.request.method == 'POST':
            view_class = _POST._mapping.get(view_name)
        else:
            raise HTTPException()
        if not view_class:
            raise _HTTPException(404)
        self.view = view_class()
        self.view.top_path = resource_id
        self.view.id = resource_id
        if self.view.model is not None and resource_id is not None:
            self.view.key = _ndb.Key(self.view.model, resource_id)

    def modify_view(self):
        modifications = {}
        for key, value in self.request.params.iteritems():
            if key not in modifications:
                modifications[key] = []
            modifications[key].append(value)
        for name, field in self.view._fields.iteritems():
            if not isinstance(field, _Input):
                continue
            if not name in modifications:
                continue
            try:
                value = [field._coerce(v) for v in modifications[name]]
            except (TypeError, ValueError):
                continue
            if not field._multivalued:
                value = value[-1]
            setattr(self.view, name, value)
        for name, field in self.view._fields.iteritems():
            if not field._required:
                continue
            if not isinstance(field, _Input):
                continue
            if getattr(self.view, name) is None:
                self.view.abort(400, "No %s Specified" % name)
                    

    def get_encoding(self):
        return self.encoder.encode(self.view)

    def clean_up(self):
        if _DEVELOPMENT:
            _ndb.get_context().clear_cache()

    def handle_error(self, exception):
        if _DEVELOPMENT:
            traceback.print_exc()
        if isinstance(exception, _HTTPException):
            self.response.set_status(exception.code, exception.message)
            self.response.write(
                self.encoder.make_exception_response(exception))
        else:
            raise exception

    encoder = None
    encoders = [_XMLEncoder, _HTMLEncoder]


class Hydro(webapp2.WSGIApplication):
    """The application."""

    def __init__(self, template_path=None, default_template=None, **kwargs):

        if template_path is not None:
            _HTMLEncoder._template_path = template_path

        if default_template is not None:
            _ViewBase.template = default_template

        super(Hydro, self).__init__(
            [
                webapp2.Route('/', Handler),
                webapp2.Route('/<view_name>', Handler),
                webapp2.Route('/<view_name>/', Handler),
                webapp2.Route('/<view_name>/<resource_id>', Handler),
                webapp2.Route('<:.*>', Handler),
            ],
            config=kwargs,
        )

    def enable_appstats(self):
        return recording.appstats_wsgi_middleware(self)


Encoder = _Encoder
Handler = _Handler

View = _View
GET = _GET
POST = _POST
Collection = _Collection

Get = _GET
Post = _POST




Inherited = _Inherited

""" Properties """
String = _StringInput
Integer = _IntegerInput
Float = _FloatInput
Boolean = _BooleanInput

Input = _Input
StringInput = _StringInput
IntegerInput = _IntegerInput
FloatInput = _FloatInput
BooleanInput = _BooleanInput
BlobInput = _BlobInput

Field = _String

Meta = _Meta

Serial = _Serial

Static = _Static
Computed = _Computed

Filter = _Filter
NestedModel = _NestedModel
SerialNestedModel = _SerialNestedModel

NestedView = _NestedView

""" Exceptions """
HTTPException = _HTTPException


Generic = Field
Output = _Output
Element = Field

transaction = _ndb.transactional
mail = _mail
DEVELOPMENT = _DEVELOPMENT

Error = HTTPException

"""

EXCEPTIONS
HTTPException

VIEWS
Get
Post

FIELDS
Generic
Inherited
Localized
StringInput
FloatInput
BooleanInput
IntegerInput



"""


