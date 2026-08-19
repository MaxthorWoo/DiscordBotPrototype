import reflex as rx

config = rx.Config(
    app_name="dashboard_app",

    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(
                accent_color="plum",
                gray_color="mauve",
                radius="medium",
            ),
        ),
    ],
)