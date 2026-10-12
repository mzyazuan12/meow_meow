#import <AppKit/AppKit.h>
#import <Accelerate/Accelerate.h>
#import <CoreGraphics/CoreGraphics.h>
#import <CoreMedia/CoreMedia.h>
#import <CoreVideo/CoreVideo.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>
#import <dlfcn.h>
#import <mach/mach_time.h>
#import <math.h>
#import <os/lock.h>
#import <stdlib.h>
#import <time.h>

#define LL_MAX_SIDE 1600.0
// The window list costs ~15 ms; resizes and closes are noticed this often.
#define LL_WINDOW_CHECK 0.5
#define LL_STREAM_RETRY 3.0

static CGImageRef (*ll_capture)(CGRect, uint32_t, uint32_t, uint32_t) = NULL;

static double ll_now(void) {
    return (double)clock_gettime_nsec_np(CLOCK_UPTIME_RAW) / 1e9;
}

static void load_capture(void) {
    if (!ll_capture) ll_capture = dlsym(RTLD_DEFAULT, "CGWindowListCreateImage");
}

static int roblox_window(CGRect *bounds) {
    CFArrayRef info = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements, kCGNullWindowID);
    if (!info) return 0;
    int found = 0;
    double best = 0;
    for (CFIndex i = 0; i < CFArrayGetCount(info); i++) {
        CFDictionaryRef d = CFArrayGetValueAtIndex(info, i);
        CFStringRef owner = CFDictionaryGetValue(d, kCGWindowOwnerName);
        if (!owner) continue;
        BOOL player = CFStringCompare(owner, CFSTR("Roblox"), kCFCompareCaseInsensitive) == kCFCompareEqualTo
                   || CFStringCompare(owner, CFSTR("RobloxPlayer"), kCFCompareCaseInsensitive) == kCFCompareEqualTo
                   || CFStringCompare(owner, CFSTR("RobloxPlayerBeta"), kCFCompareCaseInsensitive) == kCFCompareEqualTo;
        if (!player) continue;
        int layer = 0, wid = 0;
        CFNumberGetValue(CFDictionaryGetValue(d, kCGWindowLayer), kCFNumberIntType, &layer);
        CFNumberGetValue(CFDictionaryGetValue(d, kCGWindowNumber), kCFNumberIntType, &wid);
        CGRect r = CGRectZero;
        CGRectMakeWithDictionaryRepresentation(CFDictionaryGetValue(d, kCGWindowBounds), &r);
        double area = r.size.width * r.size.height;
        if (layer == 0 && area > best && r.size.width > 200 && r.size.height > 200) {
            best = area;
            found = wid;
            if (bounds) *bounds = r;
        }
    }
    CFRelease(info);
    return found;
}

// --- one-shot capture (macOS 11 to 12.2, or when the stream is unavailable) ----

static int grab_once(int wid, unsigned char **out, int *w, int *h) {
    load_capture();
    if (!ll_capture) return 0;
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

    if (W < 200 || H < 200 || W > 8000 || H > 8000) {
        CGImageRelease(img);
        return 0;
    }
    // Resize directly into a bounded capture buffer, instead of allocating
    // the full Retina screen and discarding every second/third pixel.
    double factor = fmax(1.0, fmax((double)W / LL_MAX_SIDE, (double)H / LL_MAX_SIDE));
    W = (size_t)((double)W / factor);
    H = (size_t)((double)H / factor);
    unsigned char *buf = calloc(W * H, 4);
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
    CGContextRef ctx = buf ? CGBitmapContextCreate(buf, W, H, 8, W * 4, cs, kCGImageAlphaPremultipliedLast) : NULL;
    CGColorSpaceRelease(cs);
    if (!ctx) {
        free(buf);
        CGImageRelease(img);
        return 0;
    }
    CGContextSetInterpolationQuality(ctx, kCGInterpolationHigh);
    CGContextDrawImage(ctx, CGRectMake(0, 0, W, H), img);
    CGContextRelease(ctx);
    CGImageRelease(img);

    *out = buf;
    *w = (int)W;
    *h = (int)H;
    return 1;
}

// --- continuous capture -------------------------------------------------------
// A one-shot window capture costs ~100 ms on current macOS. The stream keeps
// the newest complete frame, so a grab is only a copy of it.

static os_unfair_lock ll_lock = OS_UNFAIR_LOCK_INIT;
static CVPixelBufferRef ll_latest = NULL;  // guarded by ll_lock
static long ll_generation = 0;             // guarded by ll_lock
static long ll_sequence = 0;               // guarded by ll_lock: number of ll_latest
static double ll_valid_at = 0;             // guarded by ll_lock: last moment ll_latest was on screen
static double ll_requested_at = -1e9;      // capture thread only

// When the frame was on screen, on ll_now's clock.
static double ll_frame_time(CFDictionaryRef info) API_AVAILABLE(macos(12.3)) {
    static mach_timebase_info_data_t base;
    if (!base.denom) mach_timebase_info(&base);
    CFNumberRef value = CFDictionaryGetValue(info, (__bridge CFStringRef)SCStreamFrameInfoDisplayTime);
    uint64_t ticks = 0;
    double now = ll_now();
    if (value && base.denom && CFNumberGetValue(value, kCFNumberSInt64Type, &ticks) && ticks) {
        double at = (double)ticks * base.numer / base.denom / 1e9;
        if (at <= now + 0.001 && now - at < 1.0) return at;
    }
    return now;
}

static dispatch_queue_t ll_queue(void) {
    static dispatch_queue_t queue;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        queue = dispatch_queue_create("autotype.llcap", DISPATCH_QUEUE_SERIAL);
    });
    return queue;
}

static void ll_drop_latest(long generation) {
    CVPixelBufferRef old = NULL;
    os_unfair_lock_lock(&ll_lock);
    if (generation < 0 || generation == ll_generation) {
        old = ll_latest;
        ll_latest = NULL;
    }
    os_unfair_lock_unlock(&ll_lock);
    if (old) CVPixelBufferRelease(old);
}

API_AVAILABLE(macos(12.3))
@interface LLOutput : NSObject <SCStreamOutput, SCStreamDelegate>
@property(nonatomic) long generation;
@end

static SCStream *ll_stream API_AVAILABLE(macos(12.3)) = nil;  // ll_queue only
static LLOutput *ll_output API_AVAILABLE(macos(12.3)) = nil;  // ll_queue only

@implementation LLOutput
- (void)stream:(SCStream *)stream didOutputSampleBuffer:(CMSampleBufferRef)sample ofType:(SCStreamOutputType)type {
    if (type != SCStreamOutputTypeScreen || !CMSampleBufferIsValid(sample)) return;
    CFArrayRef attachments = CMSampleBufferGetSampleAttachmentsArray(sample, false);
    if (!attachments || CFArrayGetCount(attachments) < 1) return;
    CFDictionaryRef info = CFArrayGetValueAtIndex(attachments, 0);
    CFNumberRef status = CFDictionaryGetValue(info, (__bridge CFStringRef)SCStreamFrameInfoStatus);
    long value = -1;
    if (!status || !CFNumberGetValue(status, kCFNumberLongType, &value)) return;
    double at = ll_frame_time(info);
    if (value == SCFrameStatusIdle) {
        // Nothing changed on screen, so the stored frame is still current.
        os_unfair_lock_lock(&ll_lock);
        if (self.generation == ll_generation && ll_latest) ll_valid_at = fmax(ll_valid_at, at);
        os_unfair_lock_unlock(&ll_lock);
        return;
    }
    // Blank or suspended frames are not the game.
    if (value != SCFrameStatusComplete) return;
    CVPixelBufferRef pixels = CMSampleBufferGetImageBuffer(sample);
    if (!pixels) return;
    CVPixelBufferRetain(pixels);
    CVPixelBufferRef old = NULL;
    os_unfair_lock_lock(&ll_lock);
    if (self.generation == ll_generation) {
        old = ll_latest;
        ll_latest = pixels;
        pixels = NULL;
        ll_sequence++;
        ll_valid_at = at;
    }
    os_unfair_lock_unlock(&ll_lock);
    if (pixels) CVPixelBufferRelease(pixels);
    if (old) CVPixelBufferRelease(old);
}

- (void)stream:(SCStream *)stream didStopWithError:(NSError *)error {
    ll_drop_latest(self.generation);
    dispatch_async(ll_queue(), ^{
        if (ll_output == self) {
            ll_stream = nil;
            ll_output = nil;
        }
    });
}
@end

static void ll_stop_stream(void) API_AVAILABLE(macos(12.3)) {
    if (ll_stream) [ll_stream stopCaptureWithCompletionHandler:^(NSError *error) {}];
    ll_stream = nil;
    ll_output = nil;
}

static void ll_start_stream(long generation, int wid) API_AVAILABLE(macos(12.3)) {
    [SCShareableContent getShareableContentExcludingDesktopWindows:YES onScreenWindowsOnly:YES
                                                 completionHandler:^(SCShareableContent *content, NSError *error) {
        dispatch_async(ll_queue(), ^{
            os_unfair_lock_lock(&ll_lock);
            BOOL current = generation == ll_generation;
            os_unfair_lock_unlock(&ll_lock);
            if (!current || !content) return;
            SCWindow *target = nil;
            for (SCWindow *window in content.windows) {
                if (window.windowID == (CGWindowID)wid) {
                    target = window;
                    break;
                }
            }
            if (!target || target.frame.size.width < 200 || target.frame.size.height < 200) return;
            SCContentFilter *filter = [[SCContentFilter alloc] initWithDesktopIndependentWindow:target];
            double scale = 0;
            if (@available(macOS 14.0, *)) scale = filter.pointPixelScale;
            if (scale < 1) scale = NSScreen.mainScreen.backingScaleFactor;
            if (scale < 1) scale = 1;
            double pw = target.frame.size.width * scale, ph = target.frame.size.height * scale;
            double factor = fmax(1.0, fmax(pw / LL_MAX_SIDE, ph / LL_MAX_SIDE));
            SCStreamConfiguration *config = [[SCStreamConfiguration alloc] init];
            config.width = (size_t)(pw / factor);
            config.height = (size_t)(ph / factor);
            config.pixelFormat = kCVPixelFormatType_32BGRA;
            // The reader's colour thresholds match one-shot captures, which are sRGB.
            config.colorSpaceName = kCGColorSpaceSRGB;
            config.showsCursor = NO;
            config.queueDepth = 4;
            config.minimumFrameInterval = CMTimeMake(1, 60);
            if (@available(macOS 14.0, *)) {
                config.ignoreShadowsSingleWindow = YES;
                config.captureResolution = SCCaptureResolutionBest;
            }
            LLOutput *output = [[LLOutput alloc] init];
            output.generation = generation;
            SCStream *stream = [[SCStream alloc] initWithFilter:filter configuration:config delegate:output];
            NSError *addError = nil;
            if (![stream addStreamOutput:output type:SCStreamOutputTypeScreen sampleHandlerQueue:ll_queue() error:&addError]) return;
            ll_stop_stream();
            ll_stream = stream;
            ll_output = output;
            [stream startCaptureWithCompletionHandler:^(NSError *startError) {
                if (!startError) return;
                dispatch_async(ll_queue(), ^{
                    if (ll_output == output) {
                        ll_stream = nil;
                        ll_output = nil;
                    }
                });
            }];
        });
    }];
}

static void ll_request_stream(int wid) API_AVAILABLE(macos(12.3)) {
    os_unfair_lock_lock(&ll_lock);
    long generation = ++ll_generation;
    os_unfair_lock_unlock(&ll_lock);
    ll_drop_latest(-1);
    ll_requested_at = ll_now();
    dispatch_async(ll_queue(), ^{
        ll_stop_stream();
        if (wid) ll_start_stream(generation, wid);
    });
}

// 2 without a copy when the newest frame is *seq and refresh is off.
static int ll_copy_latest(unsigned char **out, int *w, int *h, long *seq, double *valid_at, int refresh) {
    os_unfair_lock_lock(&ll_lock);
    CVPixelBufferRef pixels = ll_latest;
    long number = ll_sequence;
    double at = ll_valid_at;
    BOOL same = pixels && !refresh && number == *seq;
    if (pixels && !same) CVPixelBufferRetain(pixels);
    os_unfair_lock_unlock(&ll_lock);
    if (same) return 2;
    if (!pixels) return 0;
    int ok = 0;
    if (CVPixelBufferLockBaseAddress(pixels, kCVPixelBufferLock_ReadOnly) == kCVReturnSuccess) {
        size_t W = CVPixelBufferGetWidth(pixels), H = CVPixelBufferGetHeight(pixels);
        unsigned char *base = CVPixelBufferGetBaseAddress(pixels);
        unsigned char *buf = (base && W >= 200 && H >= 200 && W <= 8000 && H <= 8000) ? malloc(W * H * 4) : NULL;
        if (buf) {
            vImage_Buffer src = {base, H, W, CVPixelBufferGetBytesPerRow(pixels)};
            vImage_Buffer dst = {buf, H, W, W * 4};
            const uint8_t bgra_to_rgba[4] = {2, 1, 0, 3};
            if (vImagePermuteChannels_ARGB8888(&src, &dst, bgra_to_rgba, kvImageNoFlags) == kvImageNoError) {
                *out = buf;
                *w = (int)W;
                *h = (int)H;
                *seq = number;
                *valid_at = at;
                ok = 1;
            } else {
                free(buf);
            }
        }
        CVPixelBufferUnlockBaseAddress(pixels, kCVPixelBufferLock_ReadOnly);
    }
    CVPixelBufferRelease(pixels);
    return ok;
}

static int ll_window = 0;
static CGRect ll_bounds;
static double ll_checked_at = -1e9;

int ll_grab_next(unsigned char **out, int *w, int *h, long *seq, double *age, int refresh);

int ll_grab(unsigned char **out, int *w, int *h) {
    long seq = 0;
    double age = 0;
    return ll_grab_next(out, w, h, &seq, &age, 1);
}

// The newest frame, or 2 without a copy if it is still frame *seq (unless
// refresh is set). On 1, *seq is the frame's number, 0 for a one-shot
// capture, and *age how long ago the screen last showed it.
int ll_grab_next(unsigned char **out, int *w, int *h, long *seq, double *age, int refresh) {
    if (out) *out = NULL;
    if (w) *w = 0;
    if (h) *h = 0;
    if (!out || !w || !h || !seq || !age) return 0;
    *age = 0;
    double now = ll_now();
    if (!ll_window || now - ll_checked_at >= LL_WINDOW_CHECK) {
        CGRect bounds = CGRectZero;
        int wid = roblox_window(&bounds);
        ll_checked_at = now;
        BOOL changed = wid != ll_window || !CGSizeEqualToSize(bounds.size, ll_bounds.size);
        ll_window = wid;
        ll_bounds = bounds;
        if (@available(macOS 12.3, *)) {
            if (changed) ll_request_stream(wid);
        }
    }
    if (!ll_window) return 0;
    if (@available(macOS 12.3, *)) {
        double valid_at = now;
        int copied = ll_copy_latest(out, w, h, seq, &valid_at, refresh);
        if (copied) {
            *age = fmax(0.0, now - valid_at);
            return copied;
        }
        // A stream that never delivered (denied, or the window left the
        // shareable list) is retried; one-shot capture covers the gap.
        if (now - ll_requested_at >= LL_STREAM_RETRY) ll_request_stream(ll_window);
    }
    *seq = 0;
    return grab_once(ll_window, out, w, h);
}
