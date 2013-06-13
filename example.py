from hydro import Hydro, TransientResource, StringProperty


class Test3(TransientResource):

    public_class_name = '/'
    perk = 'basic'

    test_prop = StringProperty(
        default="It works!",
    )


application = Hydro(
    config={
    }
)
