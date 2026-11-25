-- GeoPort CN 自包含版启动器（打包发布用，不依赖源码/Python）
-- 二进制位于同一 app 包内：Contents/MacOS/geoport-cn
property logFile : "/Users/user/GeoPort/logs/geoport-cn.log"
property binPattern : "MacOS/geoport-cn"

on run
	set isRunning to my isProcessRunning(binPattern)
	
	if isRunning then
		set theChoice to button returned of (display dialog "GeoPort CN 正在后台运行。" buttons {"打开页面", "停止服务", "取消"} default button "打开页面" with icon note)
		if theChoice is "打开页面" then
			my openDashboard()
		else if theChoice is "停止服务" then
			set thePort to my servingPort()
			if thePort is "" then set thePort to "54321"
			set exited to false
			try
				do shell script "curl -s --max-time 12 -X POST http://localhost:" & thePort & "/exit -o /dev/null; sleep 2; pgrep -f " & quoted form of binPattern & " >/dev/null && echo alive || echo gone"
				if result is "gone" then set exited to true
			end try
			if exited then
				display notification "GeoPort CN 已停止" with title "GeoPort CN"
			else
				try
					do shell script "pkill -f " & quoted form of binPattern
					display notification "GeoPort CN 已停止" with title "GeoPort CN"
				end try
			end if
		end if
	else
		-- 定位包内二进制（无论 app 被放到哪个目录都能找到）
		set myPath to POSIX path of (path to me)
		set binPath to myPath & "Contents/MacOS/geoport-cn"
		try
			do shell script "mkdir -p /Users/user/GeoPort/logs; touch /Users/user/GeoPort/logs/geoport-cn.log 2>/dev/null || { mv /Users/user/GeoPort/logs /Users/user/GeoPort/logs.old-root-backup 2>/dev/null; rm -rf /Users/user/GeoPort/logs; mkdir -p /Users/user/GeoPort/logs; }; ( " & quoted form of binPath & " --no-browser > " & quoted form of logFile & " 2>&1 < /dev/null & ) ; echo launched"
		on error errMsg
			display dialog "启动失败：" & errMsg & return & return & "日志：" & logFile buttons {"好"} with icon stop
			return
		end try
		repeat with i from 1 to 45
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
