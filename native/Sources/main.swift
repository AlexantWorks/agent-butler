import Cocoa

let app = NSApplication.shared
app.setActivationPolicy(.accessory)     // 菜单栏 app,无 Dock 图标
let delegate = AppDelegate()
app.delegate = delegate
app.run()
