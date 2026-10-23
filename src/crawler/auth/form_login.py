"""Pre-crawl form-based authentication with auto-MFA detection.

Supports a wide variety of login form implementations:
- Standard HTML forms (type=text, type=email)
- JS-rendered SPAs (Vue, React, Angular, Web Components)
- Forms with missing type attributes (Vue/OrangeHRM pattern)
- Multi-step flows (Google, Microsoft — username then password)
- SSO providers (SAML, OAuth, CAS, ADFS)
- Custom forms via optional selector overrides in CrawlJobConfig

MFA is auto-detected after credentials submit.  If the browser stays on an
auth-related page, the function waits for the user to complete MFA in the
visible browser window.  If it redirects to a non-auth page, it returns
immediately.
"""

import time
from typing import Optional
from urllib.parse import urlparse

from src.core.models import CrawlJobConfig


# ---------------------------------------------------------------------------
# Selector visibility timeout (ms) used when probing each candidate selector.
# JS-rendered forms (React, Web Components, etc.) may need a few seconds after
# the page "load" event before their inputs mount into the DOM.
# ---------------------------------------------------------------------------
_SELECTOR_TIMEOUT_MS = 3000

# ---------------------------------------------------------------------------
# Username / email selectors — ordered from most specific to broadest.
#
# IMPORTANT: ``input[type='text']`` does NOT match ``<input name="foo">``
# when the type attribute is omitted entirely.  Many SPA frameworks (Vue,
# React) render inputs without an explicit type.  The ``input:not([type])``
# selectors in Tier 4 handle this critical gap.
#
# The ``i`` flag in attribute selectors enables case-insensitive matching
# (e.g., name="Username" and name="username" both match ``name*='user' i``).
# ---------------------------------------------------------------------------
_USERNAME_SELECTORS = [
    # ── Tier 1: autocomplete attribute (strongest semantic signal) ─
    "input[autocomplete='username']",
    "input[autocomplete='email']",

    # ── Tier 2: type=email (unambiguous) ───────────────────────────
    "input[type='email']",

    # ── Tier 3: type=text + name/id hints ──────────────────────────
    # NOTE: Each selector appears twice — once without the CSS ``i`` flag
    # (guaranteed to work on all Playwright versions) and once with it
    # (broader matching on newer versions).  The without-i version is tried
    # first and covers the common case where names are lowercase.
    "input[type='text'][name*='user']",
    "input[type='text'][name*='login']",
    "input[type='text'][name*='email']",
    "input[type='text'][name*='acct']",
    "input[type='text'][id*='user']",
    "input[type='text'][id*='login']",
    "input[type='text'][id*='email']",

    # ── Tier 4: NO type attribute + name/id hints (Vue, React, etc.)
    # CRITICAL: ``input[type='text']`` does NOT match ``<input name="x">``
    # when type is omitted.  ``input:not([type])`` fills that gap.
    "input:not([type])[name*='user']",
    "input:not([type])[name*='login']",
    "input:not([type])[name*='email']",
    "input:not([type])[name*='acct']",
    "input:not([type])[id*='user']",
    "input:not([type])[id*='login']",
    "input:not([type])[id*='email']",

    # ── Tier 5: placeholder / aria-label hints (any type or no type)
    "input[placeholder*='user' i]",
    "input[placeholder*='email' i]",
    "input[placeholder*='login' i]",
    "input[placeholder*='Username']",
    "input[placeholder*='Email']",
    "input[aria-label*='user' i]",
    "input[aria-label*='email' i]",
    "input[aria-label*='login' i]",

    # ── Tier 6: Well-known exact names across popular platforms ────
    "input[name='username']",
    "input[name='user']",
    "input[name='log']",                          # WordPress
    "input[name='email']",
    "input[name='login']",
    "input[name='login_field']",                  # Gitea / GitHub
    "input[name='os_username']",                  # Atlassian / Jira
    "input[name='j_username']",                   # Java EE / Jenkins
    "input[name='loginfmt']",                     # Microsoft / Azure AD
    "input[name='identifier']",                   # Google / modern SSO
    "input[name='credential_0']",                 # CAS SSO
    "input[name='userid']",                       # Enterprise / banking
    "input#username",
    "input#user_login",                           # WordPress
    "input#login_field",                          # GitHub
    "input#id_username",                          # Django admin
    "input#identifierId",                         # Google login

    # ── Tier 7: Framework-specific data attributes ─────────────────
    "input[formcontrolname*='user' i]",           # Angular
    "input[formcontrolname*='email' i]",
    "input[data-testid*='user' i]",               # React testing patterns
    "input[data-testid*='email' i]",
    "input[data-testid*='login' i]",

    # ── Tier 8: Broadest fallbacks ─────────────────────────────────
    "input:not([type])",                          # Any typeless input
    "input[type='text']",                         # Any text input (absolute last)
]

# ---------------------------------------------------------------------------
# Password selectors — type=password covers ~99% of cases.  Extras are
# safety nets for custom components or forms that toggle type via JS.
# ---------------------------------------------------------------------------
_PASSWORD_SELECTORS = [
    "input[type='password']",
    "input[autocomplete='current-password']",
    "input[name='password']",
    "input[name='passwd']",                       # Unix-style / older apps
    "input[name='pwd']",                          # Microsoft / legacy
    "input[name='user_pass']",                    # WordPress
    "input[name='j_password']",                   # Java EE / Jenkins
    "input[name='os_password']",                  # Atlassian / Jira
    "input[name='credential_1']",                 # CAS SSO
    "input#password",
    "input#id_password",                          # Django admin
    "input[placeholder*='password' i]",
    "input[aria-label*='password' i]",
    "input[formcontrolname*='password' i]",       # Angular
]

# ---------------------------------------------------------------------------
# Submit button selectors — covers standard buttons, SPAs, and framework
# patterns.  "Continue" and "Next" are critical for multi-step flows
# (Google, Microsoft) where username and password are on separate screens.
# ---------------------------------------------------------------------------
_SUBMIT_SELECTORS = [
    # ── Tier 1: semantic submit elements ───────────────────────────
    "button[type='submit']",
    "input[type='submit']",

    # ── Tier 2: text matching (Playwright :has-text is case-insensitive)
    "button:has-text('Log in')",
    "button:has-text('Login')",
    "button:has-text('Log In')",
    "button:has-text('Sign in')",
    "button:has-text('Sign In')",
    "button:has-text('Signin')",
    "button:has-text('Submit')",
    "button:has-text('Continue')",                # Microsoft, Google step 1
    "button:has-text('Next')",                    # Google multi-step

    # ── Tier 3: input[value] patterns (WordPress, legacy forms) ────
    "input[value*='Log' i][type='submit']",
    "input[value*='Sign' i][type='submit']",

    # ── Tier 4: id/name patterns ───────────────────────────────────
    "button#login-button",
    "button#loginButton",
    "button#submit",
    "button[name='login']",
    "button[name='submit']",

    # ── Tier 5: ARIA and role-based (SPAs / accessible patterns) ───
    "button[aria-label*='log in' i]",
    "button[aria-label*='login' i]",
    "button[aria-label*='sign in' i]",
    "[role='button']:has-text('Log in')",
    "[role='button']:has-text('Login')",
    "[role='button']:has-text('Sign in')",

    # ── Tier 6: data-testid patterns (React / testing libs) ────────
    "button[data-testid*='login' i]",
    "button[data-testid*='submit' i]",
    "button[data-testid*='signin' i]",

    # ── Tier 7: broadest fallback — any button inside a form ───────
    "form button",
]

# ---------------------------------------------------------------------------
# Union selector used to detect *any* form input — we wait for this before
# trying individual selectors so JS-rendered forms have time to mount.
# CRITICAL: includes ``input:not([type])`` for Vue/React apps that render
# inputs without an explicit type attribute.
# ---------------------------------------------------------------------------
_ANY_INPUT_SELECTOR = ", ".join([
    "input[type='email']",
    "input[type='text']",
    "input[type='password']",
    "input:not([type])",
    "input[autocomplete='username']",
    "input[autocomplete='current-password']",
])

# ---------------------------------------------------------------------------
# URL path/query fragments that indicate auth-related pages.
# Used by the MFA wait loop to detect when the user has navigated past
# the login / MFA flow and reached authenticated content.
# ---------------------------------------------------------------------------
_AUTH_PATH_KEYWORDS = frozenset([
    # Login variants
    "login", "log-in", "log_in", "logon",
    "signin", "sign-in", "sign_in",
    # Auth infrastructure
    "auth", "authenticate", "sso",
    "saml", "oauth", "oidc", "cas", "adfs",
    "authorize", "consent", "idp",
    # MFA / 2FA / verification
    "mfa", "otp", "totp",
    "verify", "verification",
    "2fa", "two-factor", "challenge",
    "webauthn", "passkey",
    "captcha", "recaptcha",
    # Password / account recovery (still in auth flow)
    "forgot", "reset", "password", "credentials",
    "unlock",
    # Session
    "session",
    # Registration (auth-adjacent — user may be redirected here)
    "signup", "sign-up", "sign_up", "register",
])


def _is_auth_page(url: str) -> bool:
    """Heuristic: return True if *url* looks like a login / MFA / auth page.

    Checks both the path and query string, since some sites encode auth
    actions in query parameters (e.g., WordPress ``?action=login``).
    """
    parsed = urlparse(url)
    haystack = (parsed.path + "?" + parsed.query).lower()
    return any(kw in haystack for kw in _AUTH_PATH_KEYWORDS)


def _wait_for_form_render(auth_page, timeout_ms: int = 15000) -> bool:
    """Block until at least one form input is visible on the page.

    Returns True if an input appeared within *timeout_ms*, False otherwise.
    This handles JS-rendered login forms (React, Web Components, islands, etc.)
    that may not exist in the DOM at ``domcontentloaded`` or even ``load`` time.
    """
    try:
        auth_page.wait_for_selector(
            _ANY_INPUT_SELECTOR,
            state="visible",
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


def _dump_visible_inputs(auth_page) -> None:
    """Log diagnostic info about visible inputs on the page.

    Called when no selector matched, to help users debug non-standard forms.
    """
    try:
        inputs = auth_page.eval_on_selector_all(
            "input",
            """els => els
                .filter(el => el.offsetParent !== null)
                .slice(0, 10)
                .map(el => {
                    const attrs = [];
                    for (const a of ['type','name','id','placeholder','autocomplete','aria-label','formcontrolname']) {
                        if (el.getAttribute(a)) attrs.push(a + '="' + el.getAttribute(a) + '"');
                    }
                    return '<input ' + attrs.join(' ') + '>';
                })
            """,
        )
        if inputs:
            print(f"[FormAuth] DEBUG: Visible inputs on page ({len(inputs)}):")
            for inp in inputs:
                print(f"[FormAuth]   {inp}")
        else:
            print("[FormAuth] DEBUG: No visible <input> elements found on page")
    except Exception as e:
        print(f"[FormAuth] DEBUG: Could not inspect page inputs: {e}")


def _fill_field(auth_page, selectors: list, value: str, field_name: str) -> bool:
    """Try each selector in order; fill the first visible match.

    Returns True if a field was filled, False if no selector matched.
    When no selector matches, dumps visible inputs for diagnostics.
    """
    for sel in selectors:
        try:
            locator = auth_page.locator(sel).first
            if locator.is_visible(timeout=_SELECTOR_TIMEOUT_MS):
                locator.fill(value)
                print(f"[FormAuth] {field_name} filled via selector: {sel}")
                return True
        except Exception:
            continue

    print(f"[FormAuth] WARNING: Could not find a visible {field_name} field")
    _dump_visible_inputs(auth_page)
    return False


def _click_submit(auth_page, custom_selector: str = None) -> bool:
    """Try each submit selector in order; click the first visible match.

    Falls back to pressing Enter if no button was found.
    Returns True if a submit action was performed.
    """
    selectors = _SUBMIT_SELECTORS
    if custom_selector:
        selectors = [custom_selector] + list(_SUBMIT_SELECTORS)

    for sel in selectors:
        try:
            locator = auth_page.locator(sel).first
            if locator.is_visible(timeout=_SELECTOR_TIMEOUT_MS):
                locator.click()
                print(f"[FormAuth] Submit clicked via selector: {sel}")
                return True
        except Exception:
            continue

    # Fallback: press Enter (works if focus is inside the form)
    print("[FormAuth] No submit button found — pressing Enter as fallback")
    auth_page.keyboard.press("Enter")
    return True


def _is_login_form_visible(auth_page) -> bool:
    """Return True if a password input (the hallmark of a login form) is still
    visible on the page.  Used as a secondary signal to detect auth completion
    in SPAs where URL changes may not be reliable.
    """
    try:
        return auth_page.locator("input[type='password']").first.is_visible(timeout=500)
    except Exception:
        return False


def _wait_for_user_to_complete_auth(auth_page, config: CrawlJobConfig, login_url: str) -> str:
    """Wait for the user to complete multi-step auth (MFA, CAPTCHA, etc.)
    in the visible browser window.

    Polls every 2 seconds using **two signals**:
      1. **URL check**: page URL no longer looks like a login/auth page.
      2. **Form disappearance**: the password input is no longer visible
         (critical for SPAs where Vue/React router changes the view without
         a traditional navigation that updates ``page.url``).

    The wait ends when either signal fires, or ``auth_wait_seconds`` expires.

    Returns the final URL the browser landed on after auth completes.
    """
    wait_seconds = getattr(config, "auth_wait_seconds", 120)

    print(f"[FormAuth] MFA / additional auth step detected.")
    print(f"[FormAuth] Complete the auth in the browser window. Waiting up to {wait_seconds}s...")

    deadline = time.time() + wait_seconds
    poll_interval = 2  # seconds
    last_log_at = 0  # track when we last printed a countdown

    while time.time() < deadline:
        try:
            current_url = auth_page.url
        except Exception:
            # Page may have been destroyed / navigated away
            break

        # Signal 1: URL moved away from any auth-related page
        if current_url and current_url != login_url and not _is_auth_page(current_url):
            print(f"[FormAuth] Detected post-auth landing page (URL): {current_url}")
            return current_url

        # Signal 2: Login form disappeared (SPA client-side navigation)
        if not _is_login_form_visible(auth_page):
            try:
                final = auth_page.url
            except Exception:
                final = current_url
            print(f"[FormAuth] Login form disappeared — auth complete. URL: {final}")
            return final

        remaining = int(deadline - time.time())
        # Log every 10 seconds
        if remaining > 0 and (time.time() - last_log_at) >= 10:
            print(f"[FormAuth] Still waiting... {remaining}s remaining  (current: {current_url})")
            last_log_at = time.time()

        time.sleep(poll_interval)

    # Timeout reached — grab whatever URL we're on
    try:
        final_url = auth_page.url
    except Exception:
        final_url = ""

    print(f"[FormAuth] Wait finished (timeout). Final URL: {final_url}")
    return final_url


def perform_form_authentication(context, config: CrawlJobConfig) -> Optional[str]:
    """Perform pre-flight form authentication if configured.

    Opens the ``auth_login_url`` in a new page within the shared browser
    *context*, fills username + password, and submits the form.  Because
    the page is opened inside the same context, cookies set by the login
    response are automatically shared with all subsequent crawl pages.

    **Custom selectors**: If ``config.auth_username_selector``,
    ``config.auth_password_selector``, or ``config.auth_submit_selector``
    are set, they are tried first (Tier 0) before the built-in heuristics.

    **MFA auto-detection**: After submitting credentials the function checks
    the resulting URL.  If the browser is still on an auth-related page
    (login, MFA, OTP, challenge, etc.) it automatically waits for the user
    to complete the remaining steps in the visible browser window.  If the
    login redirects straight to a non-auth page, the function returns
    immediately.

    The browser **must** be launched in headed (visible) mode whenever auth
    fields are configured so the user can interact with MFA prompts if they
    appear.  The caller (SyncHTMLDownloader) handles this.

    Returns
    -------
    str or None
        The URL the browser landed on after authentication completed.
        The caller can use this as the crawl entry point instead of the
        login URL.  Returns None if auth was not attempted.
    """
    if not (config.auth_login_url and config.auth_username and config.auth_password):
        return None

    login_url = config.auth_login_url
    print(f"[FormAuth] Attempting authentication at: {login_url}")

    # ── Build selector lists (custom overrides prepended if set) ─────
    custom_user_sel = getattr(config, "auth_username_selector", None)
    custom_pass_sel = getattr(config, "auth_password_selector", None)
    custom_submit_sel = getattr(config, "auth_submit_selector", None)

    username_selectors = list(_USERNAME_SELECTORS)
    if custom_user_sel:
        username_selectors = [custom_user_sel] + username_selectors
        print(f"[FormAuth] Custom username selector: {custom_user_sel}")

    password_selectors = list(_PASSWORD_SELECTORS)
    if custom_pass_sel:
        password_selectors = [custom_pass_sel] + password_selectors
        print(f"[FormAuth] Custom password selector: {custom_pass_sel}")

    if custom_submit_sel:
        print(f"[FormAuth] Custom submit selector: {custom_submit_sel}")

    auth_page = None
    post_login_url = None

    try:
        auth_page = context.new_page()

        # ── Phase 1: Navigate & wait for JS to render ────────────────
        auth_page.goto(login_url, timeout=config.timeout_for_htmls)
        auth_page.wait_for_load_state("load")

        # Best-effort networkidle — lets async JS finish rendering.
        try:
            auth_page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        # ── Phase 1.5: Click modal trigger if configured ─────────────
        # Some sites show login in a modal/overlay instead of a dedicated
        # page.  The trigger selector points to the button that opens it.
        trigger_sel = getattr(config, "auth_trigger_selector", None)
        if trigger_sel:
            try:
                trigger = auth_page.locator(trigger_sel).first
                trigger.wait_for(state="visible", timeout=10000)
                trigger.click()
                print(f"[FormAuth] Clicked login modal trigger: {trigger_sel}")
                # Brief wait for the modal open animation
                time.sleep(1)
            except Exception as e:
                print(f"[FormAuth] WARNING: Could not click modal trigger "
                      f"'{trigger_sel}': {e}")

        # ── Phase 2: Wait for form inputs to appear in the DOM ───────
        if not _wait_for_form_render(auth_page):
            print("[FormAuth] WARNING: No form inputs detected after waiting — "
                  "authentication will likely fail")
            _dump_visible_inputs(auth_page)

        # ── Phase 3: Fill credentials ────────────────────────────────
        username_ok = _fill_field(
            auth_page, username_selectors, config.auth_username, "username"
        )
        password_ok = _fill_field(
            auth_page, password_selectors, config.auth_password, "password"
        )

        if not username_ok and not password_ok:
            print("[FormAuth] WARNING: Neither username nor password could be filled — "
                  "skipping submit")
            return None

        # ── Phase 4: Submit ──────────────────────────────────────────
        _click_submit(auth_page, custom_submit_sel)

        # ── Phase 5: Wait for post-submit navigation ─────────────────
        try:
            auth_page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            time.sleep(3)

        # ── Phase 6: Auto-detect auth outcome ────────────────────────
        # Two detection methods (both needed for SPA compatibility):
        #   A. Login form disappeared (password input gone) — works for SPAs
        #      where Vue/React router changes the view client-side.
        #   B. URL changed to a non-auth page — works for traditional
        #      server-side redirects.

        # Method A: Check if the login form is gone
        form_gone = not _is_login_form_visible(auth_page)

        try:
            current_url = auth_page.url
        except Exception:
            current_url = ""

        print(f"[FormAuth] Post-submit URL: {current_url}  (login form visible: {not form_gone})")

        if form_gone:
            # Login form disappeared — auth succeeded (SPA or redirect)
            post_login_url = current_url
            print(f"[FormAuth] Direct login success (form gone). Landed on: {post_login_url}")
        elif current_url and not _is_auth_page(current_url) and current_url != login_url:
            # Method B: URL moved to a non-auth page
            post_login_url = current_url
            print(f"[FormAuth] Direct login success (URL changed). Landed on: {post_login_url}")
        else:
            # ── Still on an auth page with form visible — MFA needed ──
            # The browser is headed (visible), so the user can interact.
            post_login_url = _wait_for_user_to_complete_auth(auth_page, config, login_url)

        print(f"[FormAuth] Authentication sequence complete.  Post-login URL: {post_login_url}")
        return post_login_url

    except Exception as e:
        print(f"[FormAuth] WARNING: Authentication may have failed: {str(e)}")
        return None
    finally:
        if auth_page:
            try:
                auth_page.close()
            except Exception:
                pass
