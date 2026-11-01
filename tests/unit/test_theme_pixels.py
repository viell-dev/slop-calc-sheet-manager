"""The native-pixel oracle accepts antialiasing while rejecting the wrong text colour."""

from tests.ui.theme_pixels import foreground_pixel


def test_thin_gtk_glyph_coverage_does_not_need_an_opaque_pixel() -> None:
    # A retained #141 GTK capture: no glyph pixel was fully opaque, but these are strong
    # mixtures of #EEF4FF text over #112233, within channel quantization.
    assert foreground_pixel((215, 222, 233), (238, 244, 255), (17, 34, 51))
    assert foreground_pixel((229, 234, 246), (238, 244, 255), (17, 34, 51))


def test_background_old_black_text_and_the_wrong_foreground_do_not_count() -> None:
    for pixel in ((17, 34, 51), (0, 0, 0), (2, 3, 5), (225, 225, 225), (255, 255, 255)):
        assert not foreground_pixel(pixel, (238, 244, 255), (17, 34, 51))
    assert not foreground_pixel((100, 100, 100), (100, 100, 100), (100, 100, 100))
