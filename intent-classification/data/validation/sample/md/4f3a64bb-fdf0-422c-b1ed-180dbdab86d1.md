<current>
<request>
You have been given comments on the previous commits you made in the repository.

You are working on an issue in the 'SECTL/SecRandom' repository.

<repository_context>
I've cloned the repository in the directory /home/runner/work/SecRandom/SecRandom (not in /tmp/inputs). Always use absolute paths when referring to files in the repository.
</repository_context>

<current_datetime>2026-05-15T13:28:39.160+00:00</current_datetime>

Consider the following problem statement:

<problem_statement>

----
*This section includes details on the pull request with code changes you have already submitted to fix the problem above.*

<pr_title>
fix: 修复Edge TTS音频格式不识别问题
</pr_title>

<pr_description>
### 问题描述
用户在使用Edge TTS播放语音时，遇到 `LibsndfileError: Error opening '...wav': Format not recognised.` 错误，导致音频无法正常播放。

### 根本原因
`edge_tts.Communicate.save()` 方法在保存Edge TTS生成的音频时，即使文件扩展名为 `.wav`，实际写入的却是MP3格式的数据。`libsndfile` 库（被 `soundfile` 使用）无法识别这种伪装成WAV的MP3文件，从而抛出格式不识别的错误。

### 解决方案
1.  **强制Edge TTS输出标准WAV格式：** 在调用 `edge_tts.Communicate` 时，明确指定 `audio_format="riff-24khz-16bit-mono-pcm"`。这确保了Edge TTS服务返回的是 `libsndfile` 可以正确解析的RIFF/WAV格式音频。
2.  **增强缓存文件校验：** 在 `VoiceCacheManager.get_voice` 方法中，新增 `_is_valid_audio` 辅助方法。在从磁盘加载缓存文件之前，会先通过 `soundfile.info()` 检查其格式有效性。如果文件格式无效（例如，旧的MP3-in-WAV文件），则会删除该文件并触发重新生成，从而自动清理并修复损坏的缓存。

此更改确保了Edge TTS生成的音频文件与播放系统之间的兼容性，解决了因格式不匹配导致的播放错误。

Fixes SECRANDOM-5E
</pr_description>

## Comments on the PR (you are @copilot in this section)

<comments>

<pr_comments>

<comment_old>
<author>@copilot-pull-request-reviewer</author>
## Pull request overview

该 PR 旨在修复 Edge TTS 生成的音频文件“扩展名为 WAV 但内容实际为 MP3”导致 `soundfile/libsndfile` 报 `Format not recognised`、进而无法播放的问题，并通过缓存校验自动清理旧的坏缓存文件。

**Changes:**
- 在生成 Edge TTS 语音时显式指定输出为 RIFF/WAV PCM（`riff-24khz-16bit-mono-pcm`）。
- 在命中磁盘缓存前新增音频有效性校验逻辑（`soundfile.info()`），无效则删除并重新生成。
- 触及到文件末尾一行的行尾字符（出现混合行尾风险）。





---

💡 <a>Add Copilot custom instructions</a> for smarter, more guided reviews. <a href="https://docs.github.com/en/copilot/customizing-copilot/adding-repository-custom-instructions-for-github-copilot">Learn how to get started</a>.
</comment_old>

</pr_comments>

<pr_reviews>

<comment_thread>
<file>app/common/voice/voice.py:472</file>
<original_commit>0b4b7e4</original_commit>

<comment_old>
<author>@copilot-pull-request-reviewer</author>
`_is_valid_audio` assumes `soundfile` imported successfully, but `sf` can be `None` (see the guarded import at the top of the file). In that case `sf.info(...)` will raise, causing the cache file to be treated as invalid and potentially deleted/re-generated on every call. Add an explicit `if sf is None:` fast-path (e.g., skip validation and avoid deleting) or provide a lightweight header check that doesn’t rely on `soundfile`.

</comment_old>

</comment_thread>

<comment_thread>
<file>app/common/voice/voice.py:476-481</file>
<original_commit>0b4b7e4</original_commit>

<comment_old>
<author>@copilot-pull-request-reviewer</author>
The `except Exception:` branch deletes the cache file for any failure from `sf.info`, including transient/OS errors (permission denied, file temporarily locked, etc.). Consider catching only the specific `soundfile` decoding/format exceptions, and log failures to remove the file instead of silently swallowing them, to avoid deleting potentially valid cache entries.

</comment_old>

</comment_thread>

<comment_thread>
<file>app/common/voice/voice.py:868</file>
<original_commit>0b4b7e4</original_commit>

<comment_old>
<author>@copilot-pull-request-reviewer</author>
This line introduces a stray carriage-return character at the end (mixed line endings). Please remove the embedded `\r`/ensure consistent LF/CRLF for the whole file to avoid formatting/lint/diff noise.
</comment_old>

</comment_thread>

</pr_reviews>

<pr_comments>

<comment_new>
<comment_id>4460152297</comment_id>
<author>@WSXYT</author>
@copilot Review the code at the location below. A potential bug has been identified by an AI
agent. Verify if this is a real issue. If it is, propose a fix; if not, explain why it's
not valid.

Location: app/common/voice/voice.py#L406

Potential issue: The `_generate_voice` function calls `edge_tts.Communicate()` with an
`audio_format` keyword argument. This parameter is not supported by the installed
version of the `edge-tts` library, causing a `TypeError` on every invocation. This
exception is caught, retried, and eventually raises a `RuntimeError`, which is then
silently handled in the calling function `_prepare_and_play`. This sequence of events
effectively and silently breaks all Edge TTS voice generation.
and
Review the code at the location below. A potential bug has been identified by an AI
agent. Verify if this is a real issue. If it is, propose a fix; if not, explain why it's
not valid.

Location: app/common/voice/voice.py#L471

Potential issue: In `_is_valid_audio`, `sf.info()` is called without first checking if
the `soundfile` library (aliased as `sf`) was successfully imported. A module-level
try/except block sets `sf` to `None` if the import fails. The unguarded call to
`sf.info()` then raises an `AttributeError`. This is caught by a broad `except
Exception` block, which incorrectly treats the audio file as invalid, deletes it, and
returns `False`. This leads to unnecessary deletion and regeneration of all cached audio
files when `soundfile` is not available.
</comment_new>

</pr_comments>

</comments>

----
The last **1** git commits in this branch are the changes you have made so far. Use those as your change commit history.
</problem_statement>


Analyze and determine if action or explanation is needed
<rules_for_making_changes>
* Start by fully understanding <problem_statement> and the <comments> before making any changes. You will only address the <comment_new> comments. Reply to new comments as you address them. Ignore comments that are not actionable or directed at you.
* For each new comment, determine:
    - If it a request for changes, a question on the code or a suggestion.
    - Is it addressed to you or someone else, e.g. "Hey @username, ..." or "@username can you ...".
    - Is it a general comment or praise.
* If there are no comments you need to address or reply to, you can stop now without exploring or explaining yourself.
* If the user's ask is not clear, you can reply to the comment and ask for clarification.
* If an action or explanation is needed, follow the steps below.
</rules_for_making_changes>





<system_reminder>
You have the capability to call multiple tools in a single response.
For maximum efficiency, whenever you need to perform multiple independent operations, ALWAYS call tools simultaneously whenever the actions can be done in parallel rather than sequentially (e.g. multiple reads/edits to different files). Especially when exploring repository, searching, reading files, viewing directories, validating changes. For example, you can read 3 different files in parallel, or edit different files in parallel. However, if some tool calls depend on previous calls to inform dependent values like the parameters, do NOT call these tools in parallel and instead call them sequentially (e.g. reading shell output from a previous command should be sequential as it requires the sessionID).
</system_reminder>

A **CI/Build Failure** has been mentioned in the problem statement, make sure to follow your instructions for addressing CI/Build Failures.
</request>
</current>
