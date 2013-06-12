from hydro import Hydro, TransientResource, StringProperty, Hidden, AnonymousUser


class Test3(TransientResource):

    public_class_name = '/'
    perk = 'basic'

    test_prop = StringProperty(
        default="It works!",
        style=Hidden(css_override=True),
    )


application = Hydro(
    config={
    }
)


