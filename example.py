from hydro import Hydro, TransientResource, StringProperty, StoredResource
from hydro import StoredStringProperty, HTTPException
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
            ('husky', "Husky"),
        ]),
        label="Choose its breed:",
        selected=None,
    )

    def client_update_hook(self, user=None):
        if not self.dogname:
            raise HTTPException(499, "You must give the poor dog a\
            name!")
        if not self.breed in ['poodle', 'chihuahua']:
            raise HTTPException(499, "Sorry, we only have the\
            technology to produce poodles and chihuahuas.")
        Dog.create(source=self)


class Dog(StoredResource):

    public_class_name = 'dog'

    dogname = StoredStringProperty()
    breed = StoredStringProperty()


application = Hydro(
    config={
    }
)
