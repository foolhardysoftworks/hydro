import hydro
from collections import OrderedDict


class DogBreeder(hydro.TransientResource):

    public_name = 'newdog'
    style = 'form'
    options = dict(submit_text="Make the Dog")

    dogname = hydro.StringProperty(
        style='input',
        default='Rover',
        label="Name the dog:",
    )
    breed = hydro.StringProperty(
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
            raise hydro.HTTPException(499, "You must give the poor dog a\
            name!")
        if not self.breed in ['poodle', 'chihuahua']:
            raise hydro.HTTPException(499, "Sorry, we only have the\
            technology to produce poodles and chihuahuas.")
        Dog.create(source=self).redirect()


class Dog(hydro.StoredResource):

    public_name = 'dog'

    heading = hydro.StaticProperty(
        value="Woof woof woof!",
        style='heading',
    )
    some_text = hydro.LinkedProperty(
        attr_name='text_maker',
        style='text',
    )

    dogname = hydro.StoredStringProperty()
    breed = hydro.StoredStringProperty()

    @property
    def text_maker(self):
        return "I am %s, your new %s." % (self.dogname.capitalize(),
                                          self.breed)

application = hydro.Hydro(
    config={
    }
)
