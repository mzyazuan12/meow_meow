#import <AppKit/AppKit.h>

static NSColor *inkColor(void) {
    return [NSColor colorWithCalibratedRed:0.043 green:0.043 blue:0.039 alpha:1];
}
static NSColor *boneColor(void) {
    return [NSColor colorWithCalibratedRed:0.945 green:0.937 blue:0.906 alpha:1];
}
static NSColor *mutedColor(void) {
    return [NSColor colorWithCalibratedRed:0.596 green:0.584 blue:0.545 alpha:1];
}
static NSColor *cardColor(void) {
    return [NSColor colorWithCalibratedRed:0.067 green:0.067 blue:0.059 alpha:1];
}
static NSColor *lineColor(void) {
    return [NSColor colorWithCalibratedRed:1 green:1 blue:1 alpha:0.14];
}

static NSTextField *label(NSString *text, CGFloat size, NSColor *color, BOOL mono) {
    NSTextField *field = [NSTextField labelWithString:text];
    field.textColor = color;
    field.backgroundColor = NSColor.clearColor;
    field.font = mono ? [NSFont monospacedSystemFontOfSize:size weight:NSFontWeightMedium]
                      : [NSFont systemFontOfSize:size weight:NSFontWeightBold];
    field.lineBreakMode = NSLineBreakByTruncatingTail;
    field.maximumNumberOfLines = 1;
    return field;
}

static void styleButton(NSButton *button, NSString *title, NSColor *bg, NSColor *fg) {
    button.bordered = NO;
    button.wantsLayer = YES;
    button.layer.backgroundColor = bg.CGColor;
    button.layer.cornerRadius = 0;
    NSMutableParagraphStyle *style = [NSMutableParagraphStyle new];
    style.alignment = NSTextAlignmentCenter;
    button.attributedTitle = [[NSAttributedString alloc] initWithString:title attributes:@{
        NSFontAttributeName: [NSFont monospacedSystemFontOfSize:12 weight:NSFontWeightSemibold],
        NSForegroundColorAttributeName: fg,
        NSParagraphStyleAttributeName: style,
        NSKernAttributeName: @1.1,
    }];
}

@interface Panel : NSObject <NSApplicationDelegate, NSTextFieldDelegate, NSWindowDelegate>
@property (nonatomic, strong) NSPanel *window;
@property (nonatomic, strong) NSTextField *usedLabel;
@property (nonatomic, strong) NSTextField *statusLabel;
@property (nonatomic, strong) NSTextField *nameField;
@property (nonatomic, strong) NSButton *casualButton;
@property (nonatomic, strong) NSButton *proButton;
@property (nonatomic, strong) NSButton *spamButton;
@property (nonatomic, strong) NSTextField *spamCaption;
@property (nonatomic, strong) NSTextField *spamField;
@property (nonatomic, strong) NSTextField *phaseLabel;
@property (nonatomic, strong) NSTextField *turnLabel;
@property (nonatomic, strong) NSView *cardView;
@property (nonatomic, strong) NSButton *resetButton;
@property (nonatomic, strong) NSScrollView *logScroll;
@property (nonatomic, strong) NSTextField *promptLabel;
@property (nonatomic, strong) NSTextField *choice1;
@property (nonatomic, strong) NSTextField *choice2;
@property (nonatomic, strong) NSTextField *choice3;
@property (nonatomic, strong) NSTextField *typeLabel;
@property (nonatomic, strong) NSTextField *trapLabel;
@property (nonatomic, strong) NSButton *armButton;
@property (nonatomic, strong) NSButton *pauseButton;
@property (nonatomic, strong) NSButton *confirmButton;
@property (nonatomic, strong) NSTextView *logView;
@property (nonatomic) BOOL casual;
@property (nonatomic) BOOL armed;
@end

@implementation Panel

- (void)send:(NSString *)line {
    printf("%s\n", line.UTF8String);
    fflush(stdout);
}

- (NSButton *)button:(NSString *)title action:(SEL)action frame:(NSRect)frame bg:(NSColor *)bg fg:(NSColor *)fg {
    NSButton *button = [[NSButton alloc] initWithFrame:frame];
    button.target = self;
    button.action = action;
    styleButton(button, title, bg, fg);
    return button;
}

- (void)applicationDidFinishLaunching:(NSNotification *)note {
    self.casual = YES;
    NSRect screen = [NSScreen mainScreen].visibleFrame;
    CGFloat width = 420;
    CGFloat height = 700;
    NSRect frame = NSMakeRect(NSMaxX(screen) - width - 28, NSMinY(screen) + 36, width, height);
    self.window = [[NSPanel alloc] initWithContentRect:frame
                                               styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskNonactivatingPanel
                                                 backing:NSBackingStoreBuffered
                                                   defer:NO];
    self.window.title = @"Last Letter";
    self.window.delegate = self;
    self.window.appearance = [NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
    self.window.backgroundColor = inkColor();
    self.window.level = NSFloatingWindowLevel;
    self.window.hidesOnDeactivate = NO;
    [self.window setCollectionBehavior:NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary];
    NSView *root = self.window.contentView;
    root.wantsLayer = YES;
    root.layer.backgroundColor = inkColor().CGColor;

    self.usedLabel = label(@"USED 0", 11, mutedColor(), YES);
    self.usedLabel.frame = NSMakeRect(250, 658, 150, 18);
    self.usedLabel.alignment = NSTextAlignmentRight;
    [root addSubview:self.usedLabel];

    NSTextField *title = label(@"LAST LETTER", 22, boneColor(), NO);
    title.frame = NSMakeRect(18, 650, 230, 30);
    [root addSubview:title];

    NSTextField *kicker = label(@"DYOE   ·   FEATHERINE", 11, mutedColor(), YES);
    kicker.frame = NSMakeRect(18, 628, 384, 16);
    [root addSubview:kicker];

    self.statusLabel = label(@"LOADING DICTIONARY", 11, mutedColor(), YES);
    self.statusLabel.frame = NSMakeRect(18, 608, 384, 16);
    [root addSubview:self.statusLabel];

    NSTextField *you = label(@"YOU", 11, mutedColor(), YES);
    you.frame = NSMakeRect(18, 574, 36, 20);
    [root addSubview:you];

    self.nameField = [[NSTextField alloc] initWithFrame:NSMakeRect(58, 570, 344, 28)];
    self.nameField.font = [NSFont monospacedSystemFontOfSize:13 weight:NSFontWeightMedium];
    self.nameField.textColor = boneColor();
    self.nameField.backgroundColor = cardColor();
    self.nameField.delegate = self;
    self.nameField.bezeled = NO;
    self.nameField.drawsBackground = YES;
    self.nameField.focusRingType = NSFocusRingTypeNone;
    [root addSubview:self.nameField];

    self.casualButton = [self button:@"CASUAL" action:@selector(casual:) frame:NSMakeRect(18, 536, 124, 32) bg:boneColor() fg:inkColor()];
    self.proButton = [self button:@"PRO" action:@selector(pro:) frame:NSMakeRect(148, 536, 124, 32) bg:cardColor() fg:boneColor()];
    self.spamButton = [self button:@"SPAM" action:@selector(spam:) frame:NSMakeRect(278, 536, 124, 32) bg:cardColor() fg:boneColor()];
    [root addSubview:self.casualButton];
    [root addSubview:self.proButton];
    [root addSubview:self.spamButton];

    self.spamCaption = label(@"HYBRID SUFFIXES", 11, mutedColor(), YES);
    self.spamCaption.frame = NSMakeRect(18, 508, 384, 16);
    self.spamCaption.hidden = YES;
    [root addSubview:self.spamCaption];

    self.spamField = [[NSTextField alloc] initWithFrame:NSMakeRect(18, 476, 384, 28)];
    self.spamField.font = [NSFont monospacedSystemFontOfSize:13 weight:NSFontWeightMedium];
    self.spamField.textColor = boneColor();
    self.spamField.backgroundColor = cardColor();
    self.spamField.delegate = self;
    self.spamField.bezeled = NO;
    self.spamField.drawsBackground = YES;
    self.spamField.focusRingType = NSFocusRingTypeNone;
    self.spamField.placeholderString = @"endings, commas or spaces";
    self.spamField.hidden = YES;
    self.spamField.wantsLayer = YES;
    self.spamField.layer.borderWidth = 1;
    self.spamField.layer.borderColor = lineColor().CGColor;
    [root addSubview:self.spamField];

    self.phaseLabel = label(@"R1   ·   PHASE 1", 12, boneColor(), YES);
    self.phaseLabel.frame = NSMakeRect(18, 496, 384, 18);
    [root addSubview:self.phaseLabel];

    self.turnLabel = label(@"WAITING", 12, boneColor(), YES);
    self.turnLabel.frame = NSMakeRect(18, 474, 228, 18);
    [root addSubview:self.turnLabel];
    self.confirmButton = [self button:@"It's your turn?" action:@selector(confirm:) frame:NSMakeRect(250, 470, 152, 26) bg:cardColor() fg:boneColor()];
    [root addSubview:self.confirmButton];

    NSView *card = [[NSView alloc] initWithFrame:NSMakeRect(18, 168, 384, 296)];
    self.cardView = card;
    card.wantsLayer = YES;
    card.layer.backgroundColor = cardColor().CGColor;
    card.layer.borderColor = lineColor().CGColor;
    card.layer.borderWidth = 1;
    [root addSubview:card];

    NSTextField *pCap = label(@"PROMPT", 10, mutedColor(), YES);
    pCap.frame = NSMakeRect(16, 264, 350, 14);
    self.promptLabel = label(@"—", 32, boneColor(), NO);
    self.promptLabel.frame = NSMakeRect(16, 214, 350, 46);

    NSTextField *cCap = label(@"CHOICES", 10, mutedColor(), YES);
    cCap.frame = NSMakeRect(16, 192, 350, 14);
    self.choice1 = label(@"—", 13, boneColor(), YES);
    self.choice1.frame = NSMakeRect(16, 168, 350, 20);
    self.choice2 = label(@"—", 13, mutedColor(), YES);
    self.choice2.frame = NSMakeRect(16, 146, 350, 20);
    self.choice3 = label(@"—", 13, mutedColor(), YES);
    self.choice3.frame = NSMakeRect(16, 124, 350, 20);

    NSTextField *typeCap = label(@"TYPE", 10, mutedColor(), YES);
    typeCap.frame = NSMakeRect(16, 98, 200, 14);
    self.typeLabel = label(@"—", 15, boneColor(), YES);
    self.typeLabel.frame = NSMakeRect(16, 70, 210, 24);
    NSTextField *trapCap = label(@"TRAP", 10, mutedColor(), YES);
    trapCap.frame = NSMakeRect(236, 98, 130, 14);
    self.trapLabel = label(@"—", 15, mutedColor(), YES);
    self.trapLabel.frame = NSMakeRect(236, 70, 130, 24);

    for (NSView *view in @[pCap, self.promptLabel, cCap, self.choice1, self.choice2, self.choice3, typeCap, self.typeLabel, trapCap, self.trapLabel]) {
        [card addSubview:view];
    }

    self.armButton = [self button:@"ARM" action:@selector(arm:) frame:NSMakeRect(18, 118, 124, 36) bg:cardColor() fg:boneColor()];
    self.pauseButton = [self button:@"PAUSE" action:@selector(pause:) frame:NSMakeRect(148, 118, 124, 36) bg:cardColor() fg:boneColor()];
    self.resetButton = [self button:@"NEW GAME" action:@selector(newGame:) frame:NSMakeRect(278, 118, 124, 36) bg:cardColor() fg:boneColor()];
    [root addSubview:self.armButton];
    [root addSubview:self.pauseButton];
    [root addSubview:self.resetButton];

    NSScrollView *scroll = [[NSScrollView alloc] initWithFrame:NSMakeRect(18, 16, 384, 92)];
    self.logScroll = scroll;
    scroll.drawsBackground = NO;
    scroll.hasVerticalScroller = YES;
    self.logView = [[NSTextView alloc] initWithFrame:scroll.bounds];
    self.logView.editable = NO;
    self.logView.drawsBackground = NO;
    self.logView.font = [NSFont monospacedSystemFontOfSize:11 weight:NSFontWeightRegular];
    self.logView.textColor = mutedColor();
    self.logView.string = @"Watching Roblox.";
    scroll.documentView = self.logView;
    [root addSubview:scroll];

    // Stay visible without becoming the active app. Stealing key focus from
    // Roblox drops the synthetic keys until the player clicks the game.
    self.window.becomesKeyOnlyIfNeeded = YES;
    [self.window orderFrontRegardless];
    [self startReader];
}

- (void)startReader {
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        char buf[4096];
        while (fgets(buf, sizeof(buf), stdin)) {
            NSString *line = [[NSString alloc] initWithUTF8String:buf];
            line = [line stringByTrimmingCharactersInSet:[NSCharacterSet newlineCharacterSet]];
            if (!line.length) continue;
            NSRange tab = [line rangeOfString:@"\t"];
            NSString *key = tab.location == NSNotFound ? line : [line substringToIndex:tab.location];
            NSString *value = tab.location == NSNotFound ? @"" : [line substringFromIndex:tab.location + 1];
            dispatch_async(dispatch_get_main_queue(), ^{
                [self apply:key value:value];
            });
        }
    });
}

- (void)apply:(NSString *)key value:(NSString *)value {
    if ([key isEqualToString:@"STATUS"]) self.statusLabel.stringValue = value;
    else if ([key isEqualToString:@"PHASE"]) self.phaseLabel.stringValue = value;
    else if ([key isEqualToString:@"TURN"]) self.turnLabel.stringValue = value;
    else if ([key isEqualToString:@"PROMPT"]) [self showPrompt:value];
    else if ([key isEqualToString:@"C1"]) self.choice1.stringValue = value.length ? value : @"—";
    else if ([key isEqualToString:@"C2"]) self.choice2.stringValue = value.length ? value : @"—";
    else if ([key isEqualToString:@"C3"]) self.choice3.stringValue = value.length ? value : @"—";
    else if ([key isEqualToString:@"TYPE"]) self.typeLabel.stringValue = value.length ? value : @"—";
    else if ([key isEqualToString:@"TRAP"]) self.trapLabel.stringValue = value.length ? value : @"—";
    else if ([key isEqualToString:@"USED"]) self.usedLabel.stringValue = value;
    else if ([key isEqualToString:@"LOG"]) [self appendLog:value];
    else if ([key isEqualToString:@"NAME"] && ![self.nameField.stringValue isEqualToString:value]) self.nameField.stringValue = value;
    else if ([key isEqualToString:@"MODE"]) [self showMode:value];
    else if ([key isEqualToString:@"SPAMTEXT"] && ![self.spamField.stringValue isEqualToString:value]) self.spamField.stringValue = value;
    else if ([key isEqualToString:@"ARMED"]) [self showArmed:[value isEqualToString:@"1"]];
    else if ([key isEqualToString:@"ARMLABEL"]) styleButton(self.armButton, value, self.armed ? boneColor() : cardColor(), self.armed ? inkColor() : boneColor());
    else if ([key isEqualToString:@"PAUSELABEL"]) styleButton(self.pauseButton, value, cardColor(), boneColor());
}

- (void)showPrompt:(NSString *)value {
    NSString *text = value.length ? value : @"—";
    self.promptLabel.stringValue = text;
    if (text.length > 10) {
        self.promptLabel.font = [NSFont monospacedSystemFontOfSize:15 weight:NSFontWeightSemibold];
    } else {
        self.promptLabel.font = [NSFont systemFontOfSize:32 weight:NSFontWeightBold];
    }
}

- (void)appendLog:(NSString *)line {
    NSString *next = [self.logView.string stringByAppendingFormat:@"%@\n", line];
    NSArray *rows = [next componentsSeparatedByString:@"\n"];
    if (rows.count > 12) rows = [rows subarrayWithRange:NSMakeRange(rows.count - 12, 12)];
    self.logView.string = [rows componentsJoinedByString:@"\n"];
    [self.logView scrollToEndOfDocument:nil];
}

- (void)showMode:(NSString *)mode {
    BOOL casual = [mode isEqualToString:@"CASUAL"] || mode.length == 0;
    BOOL pro = [mode isEqualToString:@"PRO"];
    BOOL spam = [mode isEqualToString:@"SPAM"];
    if (!casual && !pro && !spam) casual = YES;
    self.casual = casual;
    styleButton(self.casualButton, @"CASUAL", casual ? boneColor() : cardColor(), casual ? inkColor() : boneColor());
    styleButton(self.proButton, @"PRO", pro ? boneColor() : cardColor(), pro ? inkColor() : boneColor());
    styleButton(self.spamButton, @"SPAM", spam ? boneColor() : cardColor(), spam ? inkColor() : boneColor());
    [self layoutForSpam:spam];
}

- (void)layoutForSpam:(BOOL)spam {
    self.spamCaption.hidden = !spam;
    self.spamField.hidden = !spam;
    if (spam) {
        self.logScroll.frame = NSMakeRect(18, 16, 384, 52);
        self.armButton.frame = NSMakeRect(18, 76, 124, 36);
        self.pauseButton.frame = NSMakeRect(148, 76, 124, 36);
        self.resetButton.frame = NSMakeRect(278, 76, 124, 36);
        self.cardView.frame = NSMakeRect(18, 122, 384, 296);
        self.turnLabel.frame = NSMakeRect(18, 428, 228, 18);
        self.confirmButton.frame = NSMakeRect(250, 424, 152, 26);
        self.phaseLabel.frame = NSMakeRect(18, 450, 384, 18);
        self.spamField.frame = NSMakeRect(18, 476, 384, 28);
        self.spamCaption.frame = NSMakeRect(18, 508, 384, 16);
        [self.window.contentView addSubview:self.spamCaption];
        [self.window.contentView addSubview:self.spamField];
        [self.window makeFirstResponder:self.spamField];
    } else {
        self.logScroll.frame = NSMakeRect(18, 16, 384, 92);
        self.armButton.frame = NSMakeRect(18, 118, 124, 36);
        self.pauseButton.frame = NSMakeRect(148, 118, 124, 36);
        self.resetButton.frame = NSMakeRect(278, 118, 124, 36);
        self.cardView.frame = NSMakeRect(18, 168, 384, 296);
        self.turnLabel.frame = NSMakeRect(18, 474, 228, 18);
        self.confirmButton.frame = NSMakeRect(250, 470, 152, 26);
        self.phaseLabel.frame = NSMakeRect(18, 496, 384, 18);
    }
}

- (void)showArmed:(BOOL)armed {
    self.armed = armed;
    styleButton(self.armButton, armed ? @"ARMED" : @"ARM", armed ? boneColor() : cardColor(), armed ? inkColor() : boneColor());
}

- (void)arm:(id)sender { [self send:@"ARM"]; }
- (void)pause:(id)sender { [self send:@"PAUSE"]; }
- (void)casual:(id)sender { [self send:@"CASUAL"]; }
- (void)pro:(id)sender { [self send:@"PRO"]; }
- (void)spam:(id)sender { [self send:@"SPAM"]; }
- (void)newGame:(id)sender { [self send:@"NEW"]; }
- (void)confirm:(id)sender { [self send:@"CONFIRM"]; }

- (void)controlTextDidChange:(NSNotification *)note {
    if (note.object == self.spamField) {
        [self send:[NSString stringWithFormat:@"SPAMTEXT\t%@", self.spamField.stringValue ?: @""]];
    } else if (note.object == self.nameField) {
        [self send:[NSString stringWithFormat:@"NAME\t%@", self.nameField.stringValue ?: @""]];
    }
}

- (void)controlTextDidEndEditing:(NSNotification *)note {
    if (note.object == self.nameField) {
        [self send:[NSString stringWithFormat:@"NAME\t%@", self.nameField.stringValue ?: @""]];
    }
}

- (void)windowWillClose:(NSNotification *)note {
    [self send:@"QUIT"];
    [NSApp terminate:nil];
}

@end

int main(void) {
    @autoreleasepool {
        setvbuf(stdout, NULL, _IOLBF, 0);
        NSApplication *app = [NSApplication sharedApplication];
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        Panel *panel = [Panel new];
        app.delegate = panel;
        [app run];
    }
    return 0;
}
