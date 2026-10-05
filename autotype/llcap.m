#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#import <dlfcn.h>
#import <stdlib.h>

static CGImageRef (*ll_capture)(CGRect, uint32_t, uint32_t, uint32_t) = NULL;

static void load_capture(void) {
    if (!ll_capture) ll_capture = dlsym(RTLD_DEFAULT, "CGWindowListCreateImage");
}

static int roblox_window(void) {
    CFArrayRef info = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements, kCGNullWindowID);
    if (!info) return 0;
    int found = 0;
    double best = 0;
    for (CFIndex i = 0; i < CFArrayGetCount(info); i++) {
        CFDictionaryRef d = CFArrayGetValueAtIndex(info, i);
        CFStringRef owner = CFDictionaryGetValue(d, kCGWindowOwnerName);
        if (!owner) continue;
        if (CFStringFind(owner, CFSTR("Roblox"), kCFCompareCaseInsensitive).location == kCFNotFound) continue;
        int layer = 0, wid = 0;
        CFNumberGetValue(CFDictionaryGetValue(d, kCGWindowLayer), kCFNumberIntType, &layer);
        CFNumberGetValue(CFDictionaryGetValue(d, kCGWindowNumber), kCFNumberIntType, &wid);
        CGRect r = CGRectZero;
        CGRectMakeWithDictionaryRepresentation(CFDictionaryGetValue(d, kCGWindowBounds), &r);
        double area = r.size.width * r.size.height;
        if (layer == 0 && area > best && r.size.width > 200 && r.size.height > 200) {
            best = area;
            found = wid;
        }
    }
    CFRelease(info);
    return found;
}

// RGBA bytes in the same top-left layout the reader scans. Caller frees *out.
int ll_grab(unsigned char **out, int *w, int *h) {
    if (out) *out = NULL;
    if (w) *w = 0;
    if (h) *h = 0;
    load_capture();
    if (!ll_capture) return 0;
    int wid = roblox_window();
    if (!wid) return 0;
    // Logical resolution first. Retina is the fallback when that capture comes back empty.
    uint32_t options[] = {
        kCGWindowImageBoundsIgnoreFraming,
        kCGWindowImageBoundsIgnoreFraming | kCGWindowImageBestResolution,
    };
    CGImageRef img = NULL;
    for (int i = 0; i < 2 && !img; i++) {
        CGImageRef attempt = ll_capture(CGRectNull, kCGWindowListOptionIncludingWindow, (uint32_t)wid, options[i]);
        if (!attempt) continue;
        if (CGImageGetWidth(attempt) > 200 && CGImageGetHeight(attempt) > 200) {
            img = attempt;
            break;
        }
        CGImageRelease(attempt);
    }
    if (!img) return 0;
    size_t W = CGImageGetWidth(img);
    size_t H = CGImageGetHeight(img);
    // A 4K grab is tens of megabytes. An 8GB laptop cannot keep one of those
    // on the heap every frame, and the tiles are still readable below this.
    if (W < 200 || H < 200 || W > 8000 || H > 8000) {
        CGImageRelease(img);
        return 0;
    }
    unsigned char *buf = calloc(W * H, 4);
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
    CGContextRef ctx = CGBitmapContextCreate(buf, W, H, 8, W * 4, cs, kCGImageAlphaPremultipliedLast);
    CGColorSpaceRelease(cs);
    if (!ctx || !buf) {
        free(buf);
        CGImageRelease(img);
        return 0;
    }
    CGContextDrawImage(ctx, CGRectMake(0, 0, W, H), img);
    CGContextRelease(ctx);
    CGImageRelease(img);
    // Keep the letter edges. Averaging a retina frame turns Y into W,
    // so this keeps one pixel and drops the rest. 1280 is enough for the tiles.
    if (W > 1280) {
        int factor = (int)((W + 1279) / 1280);
        if (factor < 2) factor = 2;
        int tw = (int)W / factor;
        int th = (int)H / factor;
        if (tw >= 200 && th >= 200) {
            unsigned char *small = malloc((size_t)tw * th * 4);
            if (small) {
                for (int y = 0; y < th; y++) {
                    const unsigned char *row = buf + (size_t)y * factor * W * 4;
                    unsigned char *dst = small + (size_t)y * tw * 4;
                    for (int x = 0; x < tw; x++) {
                        memcpy(dst + (size_t)x * 4, row + (size_t)x * factor * 4, 4);
                    }
                }
                free(buf);
                buf = small;
                W = (size_t)tw;
                H = (size_t)th;
            }
        }
    }
    *out = buf;
    *w = (int)W;
    *h = (int)H;
    return 1;
}
