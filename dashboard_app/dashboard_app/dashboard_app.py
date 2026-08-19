import reflex as rx
from .state import BroadcastState
from .pages import broadcast_page


app = rx.App()
app.add_page(broadcast_page, route="/broadcast", on_load=BroadcastState.load)
