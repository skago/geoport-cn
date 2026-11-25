-- GeoPort CN launcher: double-click app experience
--   not running  -> ask for password (system dialog), start in background, open browser
--   already running -> choose: open page / stop service
on run
	set appDir to "/Users/user/www.github.com/geoport-cn"
	set logFile to "/tmp/geoport-cn.log"
	set procPattern to "src/main.py"
	
	set isRunning to my isProcessRunning(procPattern)
	
	if isRunning then
		set theChoice to button returned of (display dialog "GeoPort CN 正在后台运行。" buttons {"打开页面", "停止服务", "取消"} default button "打开页面" with icon note)
		if theChoice is "打开页面" then
			my openDashboard(logFile)
		else if theChoice is "停止服务" then
			try
				do shell script "pkill -f " & quoted form of procPattern with administrator privileges
				display notification "GeoPort CN 已停止" with title "GeoPort CN"
			end try
		end if
	else
		try
			do shell script "cd " & quoted form of appDir & " && nohup ./.venv/bin/python src/main.py --no-browser > " & logFile & " 2>&1 & echo launched" with administrator privileges
		on error errMsg number errNum
			display dialog "启动失败：" & errMsg buttons {"好"} with icon stop
			return
		end try
		-- 等服务就绪并打开页面
		repeat with i from 1 to 20
			delay 1
			try
				set readyPort to my servingPort(logFile)
				if readyPort is not "" then exit repeat
			end try
		end repeat
		my openDashboard(logFile)
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

on servingPort(logFile)
	try
		return do shell script "grep -o 'Serving: http://localhost:[0-9]*' " & logFile & " | tail -1 | grep -o '[0-9]*$'"
	on error
		return ""
	end try
end servingPort

on openDashboard(logFile)
	set thePort to my servingPort(logFile)
	if thePort is "" then set thePort to "54321"
	open location ("http://localhost:" & thePort)
end openDashboard
