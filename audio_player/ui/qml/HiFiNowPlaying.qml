import QtQuick
import QtQuick.Controls

Rectangle {
    id: root; color: "transparent"

    property string trackTitle: ""; property string trackArtist: ""; property string trackAlbum: ""
    // cover/bg fade in as they arrive (black → content transitions are jarring)
    property string coverPath: ""; property string bgPath: ""
    property real _bgFade: 0.0
    Behavior on _bgFade { NumberAnimation { duration: 450; easing.type: Easing.OutCubic } }
    property real _coverFade: 0.0
    Behavior on _coverFade { NumberAnimation { duration: 350; easing.type: Easing.OutCubic } }
    onCoverPathChanged: { _coverFade = 0.0; if (coverPath !== "") _coverFade = 1.0 }
    onBgPathChanged: { _bgFade = 0.0; if (bgPath !== "") _bgFade = 1.0 }
    property int    positionMs: 0; property int    durationMs: 0
    property bool   isPlaying: false
    property string qualityText: ""; property string qualitySimple: ""
    property var    lyricsModel: []; property int    lyricsActiveIdx: -1
    property real   lyricsLayoutProgress: 0.0
    Behavior on lyricsLayoutProgress { NumberAnimation { duration: 400; easing.type: Easing.InOutCubic } }

    property color  accentColor: "#7c3aed"
    property string iconPrev: ""; property string iconPlay: ""; property string iconPause: ""; property string iconNext: ""

    property real   topbarOpacity: 1.0; Behavior on topbarOpacity { NumberAnimation { duration: 300 } }
    property real   buttonsOpacity: 1.0; Behavior on buttonsOpacity { NumberAnimation { duration: 300 } }
    property bool   autoHideEnabled: true; property int    autoHideSeconds: 3

    // ---- Hero 过渡（Python 侧逐帧推送，参数见 docs/immersive-qml-port-spec.md）----
    property bool   transitionActive: false
    property string enterDirection: "in"
    property string underlayPath: ""            // 切换瞬间的普通界面快照
    property real   bgFadeAlpha: 1.0            // 页面背景相对快照的透明度
    property real   titleAlpha: 1.0; property real metaAlpha: 1.0; property real ctrlAlpha: 1.0
    property real   lyricsPreviewAlpha: 1.0
    property bool   coverOverrideActive: false  // 飞行途中封面矩形走 coverOverride*
    property real   covX: 0; property real covY: 0; property real covW: 0; property real covR: 12
    // 过渡期间各组的透明度门（空闲时为 1，不影响原绑定）
    property real _bgGate: transitionActive ? bgFadeAlpha : 1.0
    property real _ctrlGate: transitionActive ? ctrlAlpha : 1.0
    property real _titleGate: transitionActive ? titleAlpha : 1.0
    property real _metaGate: transitionActive ? metaAlpha : 1.0
    property real _lyrGate: transitionActive ? lyricsPreviewAlpha : 1.0

    signal collapseRequested(); signal fullscreenRequested()
    signal playPauseClicked(); signal nextClicked(); signal prevClicked()
    signal seekRequested(int positionMs); signal lyricsToggled(bool visible)

    property real _w: Math.max(root.width, 1); property real _h: Math.max(root.height, 1); property real _p: root.lyricsLayoutProgress
    property real _coverW_art: Math.min(_h * 0.38, _w * 0.35, 380)
    property real _coverW_lyr: Math.min(_h * 0.22, _w * 0.18, 240)
    property real _coverW: _coverW_art + (_coverW_lyr - _coverW_art) * _p
    property real _coverH: _coverW
    property real _coverX_art: (_w - _coverW_art) / 2
    property real _coverX_lyr: _w * 0.08
    property real _coverX: (_coverX_art + (_coverX_lyr - _coverX_art) * _p) - (_coverW_art - _coverW) / 2
    property real _coverY: _h * (0.15 + (0.08 - 0.15) * _p)
    property real _ctrX: _w/2 + ((_coverX + _coverW/2) - _w/2) * _p
    property real _playSz: 72 + (52 - 72) * _p
    property real _sideSz: 56 + (40 - 56) * _p
    property real _gap: 16 + (10 - 16) * _p
    property real _btnMargin: 60 + (40 - 60) * _p
    property real _barTop: _h - 168 + (40 * _p)

    // ---- 最底层：切换瞬间的普通界面快照（背景在其上淡入/淡出）----
    Image { anchors.fill: parent; source: root.underlayPath
        visible: root.transitionActive && root.underlayPath !== ""
        fillMode: Image.Stretch; cache: false; asynchronous: false }

    Item { anchors.fill: parent   // 背景组：切歌交叉淡化 + hero 过渡统一走 _bgGate
        opacity: root._bgGate
        Image { anchors.fill: parent; source: root.bgPath; fillMode: Image.PreserveAspectCrop
            visible: root.bgPath !== ""; opacity: root._bgFade }
        Rectangle { anchors.fill: parent; visible: root.bgPath === ""
            gradient: Gradient { GradientStop { position:0.0; color:"#0d0d1a" } GradientStop { position:1.0; color:"#1a1a2e" } } }
        Rectangle { anchors.fill: parent; color: "#a0000000" }
    }

    Row { anchors.right:parent.right; anchors.top:parent.top; anchors.rightMargin:12; anchors.topMargin:16; spacing:8
        // 进场：过渡期强制隐藏（hover 不得抢显）；退场：随 topbarOpacity Behavior 淡出
        opacity: (root.transitionActive && root.enterDirection === "in") ? 0.0 : root.topbarOpacity
        Rectangle { width:36; height:36; radius:18; color: root.lyricsLayoutProgress>0.5 ? root.accentColor : "#19ffffff"
            Behavior on color { ColorAnimation { duration:300 } }
            Text { anchors.centerIn:parent; text:"♪"; font.pointSize:14
                color: root.lyricsLayoutProgress>0.5 ? "#fff" : "#aaa"; Behavior on color { ColorAnimation { duration:300 } } }
            MouseArea { anchors.fill:parent; cursorShape:Qt.PointingHandCursor
                onClicked: { var to=root.lyricsLayoutProgress<0.5; root.lyricsLayoutProgress=to?1.0:0.0; root.lyricsToggled(to) } } }
        Rectangle { width:36; height:36; radius:18; color:"#19ffffff"
            Text { anchors.centerIn:parent; text:"⛶"; font.pointSize:14; color:"#aaa" }
            MouseArea { anchors.fill:parent; cursorShape:Qt.PointingHandCursor; onClicked:root.fullscreenRequested() } }
        Rectangle { width:36; height:36; radius:18; color:"#19ffffff"
            Text { anchors.centerIn:parent; text:"✕"; font.pointSize:14; color:"#aaa" }
            MouseArea { anchors.fill:parent; cursorShape:Qt.PointingHandCursor; onClicked:root.collapseRequested() } } }

    Item { id: artworkLayer; anchors.fill: parent
        opacity: 1.0 - root.lyricsLayoutProgress * 0.45

        Rectangle { x:(root.coverOverrideActive?root.covX:_coverX)+3
                    y:(root.coverOverrideActive?root.covY:_coverY)+5
                    width:(root.coverOverrideActive?root.covW:_coverW)
                    height:(root.coverOverrideActive?root.covW:_coverH)
                    radius:(root.coverOverrideActive?root.covR:12); color:"#50000000" }
        Rectangle { x:(root.coverOverrideActive?root.covX:_coverX)
                    y:(root.coverOverrideActive?root.covY:_coverY)
                    width:(root.coverOverrideActive?root.covW:_coverW)
                    height:(root.coverOverrideActive?root.covW:_coverH)
                    radius:(root.coverOverrideActive?root.covR:12); clip:true
            color: root.coverPath ? "transparent" : "#1e1e40"
            Image { anchors.fill:parent; source:root.coverPath; fillMode:Image.PreserveAspectCrop
                visible:root.coverPath!==""; opacity: root._coverFade }
            Text { anchors.centerIn:parent; text:"♪"; color:"#a78bfa"; font.pointSize:Math.max(8,_coverW/6); visible:root.coverPath==="" } }
        Rectangle { x:(root.coverOverrideActive?root.covX:_coverX)
                    y:(root.coverOverrideActive?root.covY:_coverY)
                    width:(root.coverOverrideActive?root.covW:_coverW)
                    height:(root.coverOverrideActive?root.covW:_coverH)
                    radius:(root.coverOverrideActive?root.covR:12); color:"transparent"; border.color:"#14ffffff"; border.width:1 }
        Column { y:_coverY+_coverH+32
            width:_p>0.5 ? _coverW : Math.min(_w*0.7,500)
            x: _p<0.1 ? (_w-width)/2 : (_p>0.9 ? _coverX : (_w-width)/2 + (_coverX-(_w-width)/2)*_p)
            Text { text:root.trackTitle||"♪"; font.pointSize:22; font.bold:true; color:"#ffffff"
                elide:Text.ElideRight; maximumLineCount:1; width:parent.width
                opacity: root._titleGate
                transform: Translate { y: (1.0-root._titleGate)*16 }
                horizontalAlignment:_p>0.5?Text.AlignLeft:Text.AlignHCenter; bottomPadding:8 }
            Text { text:root.trackArtist||""; font.pointSize:14
                color:Qt.lighter(root.accentColor,1.3); elide:Text.ElideRight; maximumLineCount:1
                width:parent.width; opacity: root._metaGate
                transform: Translate { y: (1.0-root._metaGate)*16 }
                horizontalAlignment:_p>0.5?Text.AlignLeft:Text.AlignHCenter; bottomPadding:4 }
            Text { text:root.trackAlbum||""; font.pointSize:11; color:"#8899aa"
                elide:Text.ElideRight; maximumLineCount:1; width:parent.width
                opacity: root._metaGate
                transform: Translate { y: (1.0-root._metaGate)*16 }
                horizontalAlignment:_p>0.5?Text.AlignLeft:Text.AlignHCenter } }
    }

    Text { id:qualityLabel; visible:root.qualityText!==""
        text:_p>0.5?(root.qualitySimple||root.qualityText):root.qualityText
        opacity: (1.0 - _p * 0.35) * root._ctrlGate
        font.pointSize:10; font.letterSpacing:1; color:Qt.lighter(root.accentColor,1.2)
        x:_ctrX-200; width:400; horizontalAlignment:Text.AlignHCenter; y:_barTop-28
        MouseArea { anchors.fill:parent; cursorShape:Qt.PointingHandCursor
            onClicked: root.outputDetailRequested() } }

    Item { id:progressBar; y:_barTop
        opacity: (1.0 - _p * 0.35) * root._ctrlGate
        x:_ctrX - width/2; width: Math.min(_w*0.5,500) + (_coverW - Math.min(_w*0.5,500))*_p; height:40
        Rectangle { anchors.top:parent.top; width:parent.width; height:12; radius:6
            color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.157) }
        Rectangle { anchors.top:parent.top; height:12; radius:6; color:root.accentColor
            width: root.durationMs>0 ? parent.width*(root.positionMs/root.durationMs) : 0 }
        Text { anchors.left:parent.left; y:24; text:formatTime(root.positionMs); font.pointSize:10; color:Qt.lighter(root.accentColor,1.3) }
        Text { anchors.right:parent.right; y:24; text:formatTime(root.durationMs); font.pointSize:10; color:Qt.lighter(root.accentColor,1.3) }
        // seek on release only — a seek per mouse-move spawns a kill/restart
        // storm of ffmpeg processes (each EOF risked skipping to the next track)
        MouseArea { anchors.fill:parent; anchors.margins:-10
            cursorShape: root.isPlaying ? Qt.PointingHandCursor : Qt.ArrowCursor
            enabled: root.isPlaying && root.durationMs > 0
            property bool _scrubbing: false
            property real _scrubX: 0
            onPressed:(mouse)=>{ _scrubbing = true; _scrubX = mouse.x; mouse.accepted = true }
            onPositionChanged:(mouse)=>{ if (_scrubbing) { _scrubX = mouse.x; mouse.accepted = true } }
            onReleased:(mouse)=>{ if (_scrubbing) { _scrubbing = false
                root.seekRequested(_scrubX/parent.width*root.durationMs) } }
            onClicked:(mouse)=>root.seekRequested(mouse.x/parent.width*root.durationMs) } }

    Item { id:transportRow; anchors.bottom:parent.bottom; anchors.bottomMargin:_btnMargin
        opacity:root.buttonsOpacity * (1.0 - _p * 0.15) * root._ctrlGate; height:_playSz
        property real _tw: 2*_sideSz+_playSz+2*_gap; x:_ctrX-_tw/2; width:_tw
        Rectangle { id:prevBtn; width:_sideSz; height:_sideSz; radius:_sideSz/2; color:"transparent"
            y:(_playSz-_sideSz)/2; Image { objectName:"qPrev"; anchors.centerIn:parent; width:parent.width*0.42; height:parent.height*0.42; source:root.iconPrev; fillMode:Image.PreserveAspectFit }
            MouseArea { anchors.fill:parent; cursorShape:Qt.PointingHandCursor; onClicked:root.prevClicked() } }
        Rectangle { id:playBtn; x:_sideSz+_gap; width:_playSz; height:_playSz; radius:_playSz/2; color:root.accentColor
            Image { anchors.centerIn:parent; width:parent.width*0.45; height:parent.height*0.45
                source:root.isPlaying?root.iconPause:root.iconPlay; fillMode:Image.PreserveAspectFit; objectName:"qPlay" }
            MouseArea { anchors.fill:parent; cursorShape:Qt.PointingHandCursor; onClicked:root.playPauseClicked() } }
        Rectangle { x:_sideSz+_gap+_playSz+_gap; width:_sideSz; height:_sideSz; radius:_sideSz/2; color:"transparent"
            y:(_playSz-_sideSz)/2; Image { objectName:"qNext"; anchors.centerIn:parent; width:parent.width*0.42; height:parent.height*0.42; source:root.iconNext; fillMode:Image.PreserveAspectFit }
            MouseArea { anchors.fill:parent; cursorShape:Qt.PointingHandCursor; onClicked:root.nextClicked() } } }

    Item { id: lyricsBlock; anchors.fill:parent
        opacity: root.lyricsLayoutProgress * root._lyrGate; visible:root.lyricsLayoutProgress>0.01
        // 歌词视觉参数与 widget 版逐项对齐（docs/immersive-qml-port-spec.md §二）：
        // 统一字号随层宽缩放、当前行 accent+加粗、翻译行仅当前行显示、
        // 非当前行 #8899aa × 距离衰减 × 0.7、上下边缘 alpha 淡出
        // 字号/行距按用户验收的紧凑版校准（1280 宽下 20pt、行距 ≈37px）
        property real layerW: root.width * 0.58
        property real layerH: root.height - 64
        property int lyricFont: Math.max(18, Math.min(26, Math.floor(layerW * 0.027)))
        property real fadeTop: Math.min(56, Math.max(28, layerH * 0.16))
        property real fadeBottom: Math.min(48, Math.max(24, layerH * 0.12))
        ListView {
            id: lyricsView
            x: root.width - lyricsBlock.layerW + 12; y: 64
            width: lyricsBlock.layerW - 24; height: lyricsBlock.layerH
            clip: true
            model: root.lyricsModel
            spacing: Math.max(10, Math.floor(lyricsBlock.lyricFont * 0.6))
            currentIndex: root.lyricsActiveIdx
            preferredHighlightBegin: Math.max(0, root.height*0.44 - 64 - lyricsBlock.lyricFont)
            preferredHighlightEnd: Math.max(1, root.height*0.44 - 64)
            highlightRangeMode: ListView.StrictlyEnforceRange
            highlightMoveDuration: 350
            snapMode: ListView.SnapToItem
            delegate: Item {
                width: ListView.view.width
                height: mainText.height
                        + (modelData.translation ? transText.height + 6 : 0)
                // 双重淡出：按索引距离（widget 版 fade 公式）× 上下边缘蒙版
                opacity: {
                    var vy = y - lyricsView.contentY
                    var H = lyricsBlock.layerH
                    var a = 1.0
                    if (vy < lyricsBlock.fadeTop)
                        a *= Math.max(0, vy / lyricsBlock.fadeTop)
                    if (vy + height > H - lyricsBlock.fadeBottom)
                        a *= Math.max(0, (H - vy - height) / lyricsBlock.fadeBottom)
                    var dist = Math.abs(index - root.lyricsActiveIdx)
                    if (index !== root.lyricsActiveIdx)
                        a *= Math.max(0, 1 - dist / 6 * 0.85) * 0.7
                    return a
                }
                Text { id: mainText
                    width: parent.width
                    text: modelData.text || ""
                    font.pointSize: lyricsBlock.lyricFont
                    font.bold: index === root.lyricsActiveIdx
                    color: index === root.lyricsActiveIdx ? root.accentColor : "#8899aa"
                    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                    Behavior on color { ColorAnimation { duration: 200 } }
                }
                Text { id: transText
                    anchors.top: mainText.bottom; anchors.topMargin: 6
                    width: parent.width
                    visible: index === root.lyricsActiveIdx && !!modelData.translation
                    text: modelData.translation || ""
                    font.pointSize: Math.max(16, lyricsBlock.lyricFont - 8)
                    color: Qt.rgba(root.accentColor.r, root.accentColor.g,
                                   root.accentColor.b, 0.55)
                    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                }
            }
        }
    }

    Timer { id:hideTransportTimer; interval:root.autoHideSeconds*1000; onTriggered:{ if(root.autoHideEnabled)root.buttonsOpacity=0.0 } }
    Timer { id:hideTopbarTimer; interval:3000; onTriggered:{ root.topbarOpacity=0.0 } }
    MouseArea { anchors.fill:parent; hoverEnabled:true; z:-1
        onPositionChanged:(mouse)=>{ if(mouse.y>_h-212){ if(root.buttonsOpacity<0.9)root.buttonsOpacity=1.0; hideTransportTimer.restart() } if(mouse.x>_w-200&&mouse.y<70){ if(root.topbarOpacity<0.9)root.topbarOpacity=1.0; hideTopbarTimer.restart() } }
        onEntered:{ root.buttonsOpacity=1.0; root.topbarOpacity=1.0; hideTransportTimer.restart(); hideTopbarTimer.restart() } }

    function formatTime(ms){ if(!ms||ms<=0)return"--:--"; var s=Math.floor(ms/1000); var m=Math.floor(s/60); s=s%60; return m+":"+(s<10?"0":"")+s }
}
