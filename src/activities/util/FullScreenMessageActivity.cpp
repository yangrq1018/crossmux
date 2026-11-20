#include "FullScreenMessageActivity.h"

#include <GfxRenderer.h>

#include "fontIds.h"

void FullScreenMessageActivity::onEnter() {
  Activity::onEnter();
  drawMessage();
}

void FullScreenMessageActivity::render(RenderLock&&) { drawMessage(); }

void FullScreenMessageActivity::drawMessage() const {
  const auto height = renderer.getLineHeight(UI_10_FONT_ID);
  const auto top = (renderer.getScreenHeight() - height) / 2;

  renderer.clearScreen();
  renderer.drawCenteredText(UI_10_FONT_ID, top, text.c_str(), true, style);
  renderer.displayBuffer(refreshMode);
}
