-- GeoPort CN launcher: double-click app experience
--   not running     -> system password prompt, start in background, open browser
--   already running -> choose: open page / stop service / open log
-- Logs live at ~/GeoPort/logs/geoport-cn.log (persists across reboots).
property appDir : "/Users/user/www.github.com/geoport-cn"
property logFile : "/Users/user/GeoPort/logs/geoport-cn.log"

on run
	set isRunning to my isProcessRunning("src/main.py")
	
	if isRunning then
		set theChoice to button returned of (display dialog "GeoPort CN 正在后台运行。" buttons {"打开页面", "停止服务", "取消"} default button "打开页面" with icon note)
		if theChoice is "打开页面" then
			my openDashboard()
		else if theChoice is "停止服务" then
			try
				do shell script "pkill -f 'src/main.py'" with administrator privileges
				display notification "GeoPort CN 已停止" with title "GeoPort CN"
			end try
		end if
	else
		-- 启动：子 shell 包裹 + 切断 stdin（do shell script 的等待语义下，
		-- 直接 `cmd &` 会把 AppleScript 卡死，此结构已实测立即返回）
		try
			do shell script "mkdir -p /Users/user/GeoPort/logs && cd " & quoted form of appDir & " && ( ./.venv/bin/python src/main.py --no-browser > " & quoted form of logFile & " 2>&1 < /dev/null & ) ; echo launched" with administrator privileges
		on error errMsg
			display dialog "启动失败：" & errMsg & return & return & "日志：" & logFile buttons {"好"} with icon stop
			return
		end try
		-- 等服务就绪（最多 30 秒）并打开页面
		repeat with i from 1 to 30
			delay 1
			try
				set readyPort to my servingPort()
				if readyPort is not "" then exit repeat
			end try
		end repeat
		if my servingPort() is "" then
			display dialog "服务启动超时。请把日志发给开发者排查：" & return & logFile buttons {"好"} with icon caution
		else
			my openDashboard()
		end if
	end if
end run

on isProcessRunning(pattern)
	try
		do shell script "pgrep -f " & quoted form of pattern
		return true
	on error
		return false
	end try
end isProcessRunning

on servingPort()
	try
		return do shell script "grep -o 'Serving: http://localhost:[0-9]*' " & quoted form of logFile & " | tail -1 | grep -o '[0-9]*$'"
	on error
		return ""
	end try
end servingPort

on openDashboard()
	set thePort to my servingPort()
	if thePort is "" then set thePort to "54321"
	open location ("http://localhost:" & thePort)
end openDashboard
