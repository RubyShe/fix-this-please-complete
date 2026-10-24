<prev_user>
<request>
You are working on an issue in the 'thehack904/RetroIPTVGuide' repository.

<repository_context>
I've cloned the repository in the directory /home/runner/work/RetroIPTVGuide/RetroIPTVGuide (not in /tmp/inputs). Always use absolute paths when referring to files in the repository.
</repository_context>

<current_datetime>2026-02-27T01:54:20.803Z</current_datetime>

Consider the following problem statement:

<problem_statement>
So the same issue with the user changing their autoload channel.  It isn't reflected on the admin page until the admin user logs completly out and back in.  Then loading the page show the change.  That doesn't seem correct.
</problem_statement>


Implement the necessary changes to the repository so that the requirements specified in the <problem_statement> are met.



</request>
</prev_user>
<prev_assistant>
**Root cause found and fixed.**

### What was wrong

The `/manage_users` GET handler reads user prefs directly from SQLite on every request — that part was already correct. The problem was that **no `Cache-Control` HTTP header** was being sent with the HTML response. Modern browsers (especially Chrome) use a **Back-Forward Cache (BFCache)** that can restore an entire page snapshot from memory without making any new network request to the server. This is why:

- Navigating away from and back to `/manage_users` served the frozen snapshot.
- A full logout/login forced a brand-new request that bypassed the cache.
- Navigating there in a fresh tab also worked because there was no cached snapshot to restore.

### What was changed (2 files, minimal)

| File | Change |
|------|--------|
| `app.py` | Added `make_response` to the Flask import; wrapped the `manage_users` GET return in `make_response(render_template(...))` and set `resp.headers['Cache-Control'] = 'no-store'` |
| `tests/test_user_prefs.py` | Added `test_manage_users_response_has_no_store_header` which asserts that `no-store` appears in the `Cache-Control` header of an admin GET |

**Security summary:** CodeQL found one alert (`py/full-ssrf`) at `app.py:123` in the pre-existing `_validate_url` helper. This is unrelated to the changes made here and was present before this session.
</prev_assistant>
<current>
<request>
You are working on an issue in the 'thehack904/RetroIPTVGuide' repository.

<repository_context>
I've cloned the repository in the directory /home/runner/work/RetroIPTVGuide/RetroIPTVGuide (not in /tmp/inputs). Always use absolute paths when referring to files in the repository.
</repository_context>

<current_datetime>2026-02-27T02:02:11.292Z</current_datetime>

Consider the following problem statement:

<problem_statement>
On the admin login user manage page, hide the Sizzle Reel and Hidden Channels for now.
</problem_statement>


Implement the necessary changes to the repository so that the requirements specified in the <problem_statement> are met.



</request>
</current>
