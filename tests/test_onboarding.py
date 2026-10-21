from arc_overlay.ui.onboarding import PAGES, OnboardingWindow


def test_pages_navigation_and_finish(qapp):
    w = OnboardingWindow()
    done = []
    w.finished.connect(lambda: done.append(True))
    assert w.page == 0
    w._back.click()
    assert w.page == 0
    for _ in range(len(PAGES) - 1):
        w._next.click()
    assert w.page == len(PAGES) - 1 and w._next.text() == "Начать"
    w._next.click()
    assert done == [True]


def test_skip_finishes(qapp):
    w = OnboardingWindow()
    done = []
    w.finished.connect(lambda: done.append(True))
    w._skip.click()
    assert done == [True]
