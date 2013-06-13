from hydro import Hydro, TransientResource, StringProperty, Style


class Test3(TransientResource):

    public_class_name = '/'
    perk = 'basic'

    test_prop = StringProperty(
        default="It works!",
        style=Style(),
    )


application = Hydro(
    config={
    }
)
