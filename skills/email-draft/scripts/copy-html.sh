#!/bin/sh
# Puts an HTML email on the macOS clipboard as rich text (public.html) with a
# plain-text fallback, so Cmd+V into Gmail keeps bold, headings and lists.
set -eu
[ $# -eq 1 ] && [ -f "$1" ] || { echo "usage: $0 email.html" >&2; exit 1; }
osascript -l JavaScript - "$1" <<'JS'
ObjC.import('AppKit');
function run(argv) {
  const html = $.NSString.stringWithContentsOfFileEncodingError(argv[0], $.NSUTF8StringEncoding, null);
  const data = html.dataUsingEncoding($.NSUTF8StringEncoding);
  const text = $.NSAttributedString.alloc.initWithHTMLDocumentAttributes(data, null).string;
  const pb = $.NSPasteboard.generalPasteboard;
  pb.clearContents;
  pb.setStringForType(html, 'public.html');
  pb.setStringForType(text, 'public.utf8-plain-text');
  return 'copied ' + text.length + ' chars';
}
JS
