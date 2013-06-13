from hydro import Hydro, TransientResource, StringProperty, StoredResource
from hydro import StoredStringProperty, HTTPException, StaticProperty, LinkedProperty
from collections import OrderedDict


class DogBreeder(TransientResource):

    public_name = 'newdog'
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
        Dog.create(source=self).redirect()


class Dog(StoredResource):

    public_name = 'dog'

    heading = StaticProperty(
        value="Woof woof woof!",
        style='heading',
    )
    some_text = LinkedProperty(
        attr_name='text_maker',
        style='text',
    )

    dogname = StoredStringProperty()
    breed = StoredStringProperty()

    @property
    def text_maker(self):
        return "I am %s, your new %s." % (self.dogname.capitalize(),
                                          self.breed)

application = Hydro(
    config={
    }
)
