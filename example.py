from hydro import Hydro, TransientResource, StringProperty, StoredResource
from hydro import StoredStringProperty
from collections import OrderedDict


class DogBreeder(TransientResource):

    public_class_name = 'newdog'
    style = 'form'
    options = dict(submit_text="Make the Dog")

    dogname = StringProperty(
        style='input',
        default='Rover',
        label="Name the dog:",
    )
    breed = StringProperty(
        style='select',
        choices=OrderedDict([
            (None, "Please select a breed..."),
            ('poodle', "Poodle"),
            ('chihuahua', "Chihuahua"),
        ]),
        label="Choose its breed:",
        selected=None,
    )

    def client_update_hook(self, user):
        pass


class Dog(StoredResource):

    public_class_name = 'dog'

    breed = StoredStringProperty()
    color = StoredStringProperty()


application = Hydro(
    config={
    }
)
