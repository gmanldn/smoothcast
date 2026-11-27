"""Web queue: uploads, playback and queued items share one list with status chips."""
import portal


def test_queue_has_pinned_rows_with_status_chips_and_optimistic_upload_rows():
    text = portal._HTML
    for needle in ("function paintIncoming()", "function setLocalUploads(", "li.queue-item pinned",
                   'chip.className="chip"', "localUploadProgress(phase,received,total,note)",
                   'setLocalUploads($("videoFile").files)', "paintIncoming();\n  if(focusTarget)"):
        assert needle.replace("li.queue-item pinned", 'queue-item pinned "') in text or needle in text, needle
    # Coalesced to one repaint per frame so upload progress cannot thrash the DOM.
    assert "requestAnimationFrame(()=>{incomingPaint=0;paintIncoming()})" in text
    # The separate Incoming panel is no longer fed; rows live inside #queue.
    assert 'getElementById("queueIncomingRows")' not in text and '$("queueIncomingRows")' not in text
