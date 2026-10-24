import QtQuick
import QtQuick.Controls

Rectangle {
    id: root; color: "transparent"

    property string trackTitle: ""; property string trackArtist: ""; property string trackAlbum: ""
    property string coverPath: ""; property string bgPath: ""
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

    Image { anchors.fill: parent; source: root.bgPath; fillMode: Image.PreserveAspectCrop; visible: root.bgPath !== "" }
    Rectangle { anchors.fill: parent; visible: root.bgPath === ""
        gradient: Gradient { GradientStop { position:0.0; color:"#0d0d1a" } GradientStop { position:1.0; color:"#1a1a2e" } } }
    Rectangle { anchors.fill: parent; color: "#a0000000" }

    Row { anchors.right:parent.right; anchors.top:parent.top; anchors.rightMargin:12; anchors.topMargin:16; spacing:8; opacity:root.topbarOpacity
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

        Rectangle { x:_coverX+3; y:_coverY+5; width:_coverW; height:_coverH; radius:12; color:"#50000000" }
        Rectangle { x:_coverX; y:_coverY; width:_coverW; height:_coverH; radius:12; clip:true
            color: root.coverPath ? "transparent" : "#1e1e40"
            Image { anchors.fill:parent; source:root.coverPath; fillMode:Image.PreserveAspectCrop; visible:root.coverPath!=="" }
            Text { anchors.centerIn:parent; text:"♪"; color:"#a78bfa"; font.pointSize:Math.max(8,_coverW/6); visible:root.coverPath==="" } }
        Rectangle { x:_coverX; y:_coverY; width:_coverW; height:_coverH; radius:12; color:"transparent"; border.color:"#14ffffff"; border.width:1 }
        Column { y:_coverY+_coverH+32; width:_p>0.5 ? _coverW : Math.min(_w*0.7,500)
            x: _p<0.1 ? (_w-width)/2 : (_p>0.9 ? _coverX : (_w-width)/2 + (_coverX-(_w-width)/2)*_p)
            Text { text:root.trackTitle||"♪"; font.pointSize:22; font.bold:true; color:"#ffffff"
                elide:Text.ElideRight; maximumLineCount:1; width:parent.width
                horizontalAlignment:_p>0.5?Text.AlignLeft:Text.AlignHCenter; bottomPadding:8 }
            Text { text:root.trackArtist||""; font.pointSize:14
                color:Qt.lighter(root.accentColor,1.3); elide:Text.ElideRight; maximumLineCount:1
                width:parent.width; horizontalAlignment:_p>0.5?Text.AlignLeft:Text.AlignHCenter; bottomPadding:4 }
            Text { text:root.trackAlbum||""; font.pointSize:11; color:"#8899aa"
                elide:Text.ElideRight; maximumLineCount:1; width:parent.width
                horizontalAlignment:_p>0.5?Text.AlignLeft:Text.AlignHCenter } }
    }

    Text { id:qualityLabel; visible:root.qualityText!==""
        text:_p>0.5?(root.qualitySimple||root.qualityText):root.qualityText
        opacity: 1.0 - _p * 0.35
        font.pointSize:10; font.letterSpacing:1; color:Qt.lighter(root.accentColor,1.2)
        x:_ctrX-200; width:400; horizontalAlignment:Text.AlignHCenter; y:_barTop-28 }

    Item { id:progressBar; y:_barTop
        opacity: 1.0 - _p * 0.35
        x:_ctrX - width/2; width: Math.min(_w*0.5,500) + (_coverW - Math.min(_w*0.5,500))*_p; height:40
        Rectangle { anchors.top:parent.top; width:parent.width; height:12; radius:6
            color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.157) }
        Rectangle { anchors.top:parent.top; height:12; radius:6; color:root.accentColor
            width: root.durationMs>0 ? parent.width*(root.positionMs/root.durationMs) : 0 }
        Text { anchors.left:parent.left; y:24; text:formatTime(root.positionMs); font.pointSize:10; color:Qt.lighter(root.accentColor,1.3) }
        Text { anchors.right:parent.right; y:24; text:formatTime(root.durationMs); font.pointSize:10; color:Qt.lighter(root.accentColor,1.3) }
        MouseArea { anchors.fill:parent; anchors.margins:-10; cursorShape:Qt.PointingHandCursor
            onPositionChanged:(mouse)=>{ if(mouse.buttons&Qt.LeftButton)root.seekRequested(mouse.x/parent.width*root.durationMs) }
            onClicked:(mouse)=>root.seekRequested(mouse.x/parent.width*root.durationMs) } }

    Item { id:transportRow; anchors.bottom:parent.bottom; anchors.bottomMargin:_btnMargin
        opacity:root.buttonsOpacity * (1.0 - _p * 0.15); height:_playSz
        property real _tw: 2*_sideSz+_playSz+2*_gap; x:_ctrX-_tw/2; width:_tw
        Rectangle { id:prevBtn; width:_sideSz; height:_sideSz; radius:_sideSz/2; color:"transparent"
            y:(_playSz-_sideSz)/2; Image { anchors.centerIn:parent; width:parent.width*0.42; height:parent.height*0.42; source:root.iconPrev; fillMode:Image.PreserveAspectFit }
            MouseArea { anchors.fill:parent; cursorShape:Qt.PointingHandCursor; onClicked:root.prevClicked() } }
        Rectangle { id:playBtn; x:_sideSz+_gap; width:_playSz; height:_playSz; radius:_playSz/2; color:root.accentColor
            Image { anchors.centerIn:parent; width:parent.width*0.45; height:parent.height*0.45
                source:root.isPlaying?root.iconPause:root.iconPlay; fillMode:Image.PreserveAspectFit }
            MouseArea { anchors.fill:parent; cursorShape:Qt.PointingHandCursor; onClicked:root.playPauseClicked() } }
        Rectangle { x:_sideSz+_gap+_playSz+_gap; width:_sideSz; height:_sideSz; radius:_sideSz/2; color:"transparent"
            y:(_playSz-_sideSz)/2; Image { anchors.centerIn:parent; width:parent.width*0.42; height:parent.height*0.42; source:root.iconNext; fillMode:Image.PreserveAspectFit }
            MouseArea { anchors.fill:parent; cursorShape:Qt.PointingHandCursor; onClicked:root.nextClicked() } } }

    Item { anchors.fill:parent; opacity:root.lyricsLayoutProgress; visible:root.lyricsLayoutProgress>0.01
        ListView { id:lyricsView; anchors.centerIn:parent; width:Math.min(_w*0.6,600); height:_h*0.5
            model:root.lyricsModel; spacing:8; currentIndex:root.lyricsActiveIdx
            preferredHighlightBegin:height/2-24; preferredHighlightEnd:height/2+24
            highlightRangeMode:ListView.StrictlyEnforceRange; snapMode:ListView.SnapToItem
            delegate: Text { width:ListView.view.width; text:modelData.text||""
                font.pointSize: index===root.lyricsActiveIdx ? 18 : 14
                color: index===root.lyricsActiveIdx ? "#ffffff" : "#8899aa"
                horizontalAlignment:Text.AlignHCenter; wrapMode:Text.WordWrap
                Behavior on font.pointSize { NumberAnimation { duration:150 } }
                Behavior on color { ColorAnimation { duration:150 } } } }
    }

    Timer { id:hideTransportTimer; interval:root.autoHideSeconds*1000; onTriggered:{ if(root.autoHideEnabled)root.buttonsOpacity=0.0 } }
    Timer { id:hideTopbarTimer; interval:3000; onTriggered:{ root.topbarOpacity=0.0 } }
    MouseArea { anchors.fill:parent; hoverEnabled:true; z:-1
        onPositionChanged:(mouse)=>{ if(mouse.y>_h-212){ if(root.buttonsOpacity<0.9)root.buttonsOpacity=1.0; hideTransportTimer.restart() } if(mouse.x>_w-200&&mouse.y<70){ if(root.topbarOpacity<0.9)root.topbarOpacity=1.0; hideTopbarTimer.restart() } }
        onEntered:{ root.buttonsOpacity=1.0; root.topbarOpacity=1.0; hideTransportTimer.restart(); hideTopbarTimer.restart() } }

    function formatTime(ms){ if(!ms||ms<=0)return"--:--"; var s=Math.floor(ms/1000); var m=Math.floor(s/60); s=s%60; return m+":"+(s<10?"0":"")+s }
}
