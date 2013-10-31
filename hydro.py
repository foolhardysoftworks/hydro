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

import webapp2
import bleach  # Not included in GAE

from xml.etree.ElementTree import Element, SubElement, tostring
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
_SERVER_DOWN = False

get_request = webapp2.get_request


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

    def __init__(self, code=None, message=None):
        if code is not None:
            self.code = code
        if message is not None:
            self.message = message
        elif self.code in self.message_map:
            self.message = self.message_map[self.code]


class _Inherited(object):
    def __init__(self, *args):
        self.names = args

    def get_value(self, entity):
        for name in self.names:
            if isinstance(entity, dict):
                entity = entity[name]
            else:
                entity = getattr(entity, name)
        return entity


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

    _name = None
    _parent_class = None

    _counter = 0

    def __init__(self,
                 default=None,
                 tag=None,
                 multivalued=None,
                 indexed=None,
                 metadata=None,
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
        self._index = self._counter
        _Field._counter += 1

    def __get__(self, parent, _=None):
        if parent is None:
            return self
        if self._name in parent.__dict__:
            value = parent.__dict__[self._name]
        else:
            value = copy.deepcopy(self._default_)
        if self._multivalued:
            if value is None:
                return []
            if not isinstance(value, (list, tuple)):
                return [value]
        return value


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
        if isinstance(parent, _Model):
            self._ndb_class.__set__(self, parent, value)
        else:
            parent.__dict__[self._name] = value

    def __get__(self, parent, _=None):
        if parent is None:
            return self
        elif isinstance(self, _ndb.Property) and isinstance(parent, _Model):
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
            if isinstance(d['value'], (_View, _Model)):
                r = d['value'].as_dictionary
                d['value'] = str()
                d['contents'] = r['contents']
                d['metadata'].update(r['metadata'])
            if isinstance(d['value'], _Inherited):
                d['value'] = d['value'].get_value(self.entity)
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


class _ViewBase(_ViewAndModelBase):

    _mapping = {}
    path = None
    template = "index.html"

    @classmethod
    def create(cls, *args, **kwargs):
        return cls(*args, **kwargs)

    def _internal_read_hook(self):
        self.on_read()

    def _internal_pre_modify_hook(self):
        pass

    def _internal_post_modify_hook(self):
        self.on_submit()

    def on_submit(self):
        pass

    def on_read(self):
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
    _resource_id = None
    _resource = None

    def __init__(self, resource=None, resource_id=None):
        if isinstance(resource, basestring):
            resource_id = resource
            resource = None
        if resource_id is not None:
            self._resource_id = resource_id
        if resource is not None:
            self._resource_id = resource.key.urlsafe()
            self._resource = resource
        for name, field in self._fields.iteritems():
            if isinstance(field, _NestedView):
                if field._multivalued:
                    setattr(self, name, [])
                else:
                    subview = field._view(
                        resource_id=self._resource_id)
                    subview.model = self.model
                    setattr(self, name, subview)

    def prime(self):
        if self.model and self._resource_id and not self._resource:
            self.model.prime(self._resource_id)

    @property
    def entity(self):
        return self.resource

    @property
    def resource(self):
        if not self._resource:
            if not self.model or not self._resource_id:
                raise HTTPException(404)
            self._resource = self.model.read(self._resource_id)
        if not self._resource:
            raise HTTPException(404)
        return self._resource

    @property
    def as_dictionary(self):
        if self._as_dictionary is not None:
            return self._as_dictionary
        d = super(_View, self).as_dictionary
        if self._resource_id:
            d['metadata']['id'] = self.resource.id
        return d


class _Collection(_ViewBase):

    __metaclass__ = _MetaView

    view = None

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


class _MetaModel(_ndb.MetaModel, _MetaBase):
    def __init__(cls, name, bases, cdict):
        super(_ndb.MetaModel, cls).__init__(name, bases, cdict)
        super(_MetaBase, cls).__init__(name, bases, cdict)
        cls._properties = {}
        for name in set(dir(cls)):
            prop_ = getattr(cls, name, None)
            if (isinstance(prop_, _ndb.ModelAttribute) and not
               isinstance(prop_, _ndb.ModelKey)):
                prop_._fix_up(cls, name)
                if prop_._repeated:
                    cls._has_repeated = True
                cls._properties[prop_._name] = prop_
        cls._kind_map[cls.__name__] = cls


class _Model(_ndb.Model, _ViewAndModelBase):

    __metaclass__ = _MetaModel

    create_on_read = False
    update_on_create = False

    @classmethod
    def create(cls, name=None, update=True, parent=None, mods=None, **kwargs):
        """Create a resource.

        Create a resource instance of the given class with the
        specified name.  If the name is not specified, it is generated
        with the create_name class-method.  The resource is placed
        immediately in the thread cache, and optionally into the
        instance cache, memcache, and datastore.  Additional
        functionality can be added with the on_create hook.

        Args:
            name: A string identifying the created resource. A name
                will be generated if not specified.
            update: A boolean indicating whether or not to save the
                resource to the memcache and datastore *after* calling
                the on_create hook.
            **kwargs: Pass through keyword arguments for the
                create_name, on_create, and update methods (when
                applicable).

        Returns:
            A shiny new resource.

        Note:
           This effectively replaces the class constructor. All
           resources should be created with this method.

        """
        if not name:
            name = cls.create_name(**kwargs)
        entity = cls(id=name, parent=parent)
        for name, field in entity._fields.iteritems():
            if isinstance(field, (_NestedModel, _SerialNestedModel)):
                if not field._multivalued:
                    setattr(entity, name, field._model.create())
        if mods:
            for key, value in mods.iteritems():
                setattr(entity, key, value)
        entity._internal_create_hook(**kwargs)
        if update or cls.update_on_create:
            entity.put()
            if cls._use_instance_cache:
                cls._instance_cache[entity.key.urlsafe()] = entity
        else:
            entity.put(use_memcache=False, use_datastore=False)
        return entity

    @classmethod
    def read(cls, name, create=False, _prime=False, **kwargs):
        """Retrieve a resource

        Retrieve a resource of the given class with the specified name
        from the thread cache, instance cache, memcache, or datastore.
        If the name is not specified, it is generated with the
        create_name method.  If the resource is not found in any of
        those locations and create is true, a new resource will be
        created.  Additional functionality can be added with the
        on_read hook.  When a resource is retrieved it is
        automatically saved to the caches, i.e. if its found in the
        datastore it will be saved to the memcache, instance cache,
        and thread cache (when applicable).

        Args:
            name: A string identifying the resource to retrieve.
            create_name: A boolean indicating whether or not to create
                a name if the specified name is false.
            create: A boolean indicating whether or not to create a
                resource with the create method if the resource cannot
                be found.
            **kwargs : Pass through keyword arguments for the
                create_name, create, and on_read methods (when
                applicable).

        Returns:
            A resource, if the resource was found or create was
            true. None if the resource was not found and create was
            false.
        """

        if not name:
            return

        key = _ndb.Key(cls.__name__, name)
        key_string = key.urlsafe()

        if cls._use_instance_cache:
            resource = cls._instance_cache.get(key_string)
            if resource is not None:
                return resource

        if not key_string in cls._futures:
            cls._futures[key_string] = cls._read_tasklet(key, create, **kwargs)

        if _prime:
            return

        resource = cls._futures[key_string].get_result()

        if cls._use_instance_cache and resource is not None:
            cls._instance_cache[key_string] = resource

        return resource

    @classmethod
    @_ndb.tasklet
    def prime(cls, *args, **kwargs):
        cls.read(*args, _prime=True, **kwargs)

    @classmethod
    @_ndb.tasklet
    def _read_tasklet(cls, key, create=False, use_cache=None, use_memcache=None, **kwargs):
        resource = yield key.get_async()
        if resource:
            resource = resource._internal_read_hook(**kwargs)
            for name, field in resource._fields.iteritems():
                if isinstance(field, (_NestedModel, _SerialNestedModel)):
                    if not field._multivalued:
                        setattr(resource, name, field._model.create())
        if resource is None and (create or cls.create_on_read):
            resource = cls.create(key.string_id(), **kwargs)
        raise _ndb.Return(resource)

    def update(self, async=False, mods=None, **kwargs):
        """Save the resource.

        Modify the properties of the resource and save the resource to
        the thread cache.  If externally is true, also save the
        resource to the instance cache, memcache, and datastore (when
        applicable). Additional functionality can be added with the
        on_update hook.

        Args:
            externally: A boolean indicating whether or not to save
                the resource to the instance cache, memcache, and
                datastore (when applicable).
            modifications: A dictionary of property name/property
                values to set before updating.
            **kwargs: Pass-through keyword arguments for the on_update
                hook.

        """
        if mods:
            for key, value in mods.iteritems():
                setattr(self, key, value)
        self._internal_update_hook(**kwargs)
        if self._use_instance_cache:
            self._instance_cache[self.key.urlsafe()] = self
        future = self._update_tasklet(**kwargs)
        if async:
            return future
        return future.get_result()

    @_ndb.tasklet
    def _update_tasklet(self, **kwargs):
        yield self.put_async()
        if self._use_instance_cache:
            self._instance_cache[self.key.urlsafe()] = self
        raise _ndb.Return()

    def delete(self, **kwargs):
        """Purge the resource from existence.

        Remove the resource from the thread cache, instance cache,
        memcache, and datastore. Additional functionality can be added
        with the on_delete hook.

        Args:
            **kwargs: Pass-through keyword arguments for the on_delete
                hook.
        """
        self.on_delete(**kwargs)
        self.key.delete()

    def _internal_create_hook(self, **kwargs):
        self.on_create(**kwargs)

    def _internal_read_hook(self, **kwargs):
        self.on_read(**kwargs)
        return self

    def _internal_update_hook(self, **kwargs):
        self.on_update(**kwargs)

    def _internal_delete_hook(self, **kwargs):
        self.on_delete(**kwargs)

    @classmethod
    def create_name(cls, **kwargs):
        """Create a name for a resource.

        Generate a unique identifier using a combination of uuid1 and
        uuid4.  There is virtually no chance of collision and the
        identifier should be securely random.  This method can be
        overriden to add context to the identifier.

        Args:
            **kwargs: Not used, but here for compatibility.

        Returns:
            A unique identifier for a resource (a string).

        """
        return urlsafe_b64encode(uuid.uuid4().bytes)[0:22]

    def on_create(self, **kwargs):
        """Hook called when creating a resource.

        This method is called just after the resource is created and
        before it is saved.
        """

    def on_read(self, **kwargs):
        """Hook called when reading a resource.

        This method is called just after the resource is loaded from
        the memcache or datastore.
        """

    def on_update(self, **kwargs):
        """Hook called when updating a resource.

        This method is called just before a resource is saved to the
        instance cache, memcache, or datastore.
        """

    def on_delete(self, **kwargs):
        """Hook called when deleting a resource.

        This method is called just before a resource is deleted.
        """


    @property
    def id(self):
        return self.key.id()

    _futures = {}
    _instance_cache = {}

    _use_cache = True
    _use_instance_cache = False
    _use_memcache = True
    _use_datastore = True

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

        for k, v in d['metadata'].iteritems():
            d['metadata'][k] = cls.remove_bad_chars(unicode(v))

        if root is None:
            e = Element(d['tag'], **d['metadata'])
        else:
            e = SubElement(root, d['tag'], **d['metadata'])

        if d.get('value') is not None:
            e.text = cls.remove_bad_chars(unicode(d.get('value')))
        elif d.get('contents', []):
            pass
        else:
            e.text = " "

        for value in d.get('contents', []):
            cls.encode_dict(e, value)
        return e

    @classmethod
    def make_exception_response(cls, e):
        main = Element("error")
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
            if _SERVER_DOWN:
                raise HTTPException(503, "The server is currently down.")
            self.create_view(**self.request.route_kwargs)
            if self.request.method == 'POST' or isinstance(self.view,
                                                           _Collection):
                self.view._internal_pre_modify_hook()
                self.modify_view()
                self.view._internal_post_modify_hook()
                if not isinstance(self.view, _Collection):
                    self.create_view(**self.request.route_kwargs)
            elif self.request.method != 'GET':
                raise _HTTPException(405)
            self.view._internal_read_hook()
            self.response.write(self.get_encoding())
            self.clean_up()
            print(self.response)
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
        view_class = _View._mapping.get(view_name)
        if not view_class:
            raise _HTTPException(404)
        if issubclass(view_class, _View):
            self.view = view_class(resource_id=resource_id)
        else:
            if resource_id:
                raise _HTTPException(404)
            self.view = view_class()

    def modify_view(self):
        modifications = {}
        for key, value in self.request.params.iteritems():
            if key not in modifications:
                modifications[key] = []
            modifications[key].append(value)
        for name, field in self.view._fields.iteritems():
            if not field._modifiable or not name in modifications:
                continue
            try:
                value = [field._coerce(v) for v in modifications[name]]
            except (TypeError, ValueError):
                continue
            if not field._multivalued:
                value = value[-1]
            setattr(self.view, name, value)

    def get_encoding(self):
        return self.encoder.encode(self.view)

    def clean_up(self):
        if _DEVELOPMENT:
            _ndb.get_context().clear_cache()
        _Model._futures = {}

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

Model = _Model

View = _View
Collection = _Collection


Inherited = _Inherited

""" Properties """
String = _String
Integer = _Integer
Float = _Float
Boolean = _Boolean

Input = _Input
StringInput = _StringInput
IntegerInput = _IntegerInput
FloatInput = _FloatInput
BooleanInput = _BooleanInput
BlobInput = _BlobInput


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


transaction = _ndb.transactional
mail = _mail
DEVELOPMENT = _DEVELOPMENT


