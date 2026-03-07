-- This script batch converts .doc files to PDF using TextEdit and System Events.
-- It replaces the previous Word-based .docx conversion script to avoid
-- Microsoft Word dependencies and licensing issues.
-- It uses `find` via shell for high-performance file discovery.

on run
	set sourceFolder to choose folder with prompt "Select the folder containing .doc files to convert:"
	set fileList to getFileNames(sourceFolder)

	tell application "TextEdit"
		activate
	end tell

	repeat with aFile in fileList
		-- Since find returns POSIX paths natively now, we just coerce them to AppleScript alias objects
		set posixTarget to aFile as text

		if posixTarget ends with ".doc" then
			set newFileName to (text 1 thru -5 of posixTarget) & ".pdf"

			-- Generate a Mac HFS path for TextEdit to "open" via System Events
			set fileAlias to POSIX file posixTarget as alias

			tell application "TextEdit"
				open fileAlias
			end tell

			tell application "System Events"
				tell process "TextEdit"
					set frontmost to true
					-- Usually the menu item is "Export as PDF…" with an ellipsis (Option-semicolon)
					try
						click menu item "Export as PDF…" of menu "File" of menu bar 1
					on error
						click menu item "Export as PDF..." of menu "File" of menu bar 1
					end try

					-- wait for save sheet
					repeat until exists sheet 1 of window 1
						delay 0.1
					end repeat

					tell sheet 1 of window 1
						-- change directory by invoking "Go to Folder"
						keystroke "g" using {command down, shift down}

						-- wait for the Go To folder sheet
						repeat until exists sheet 1
							delay 0.1
						end repeat

						delay 0.2
						set the clipboard to newFileName
						keystroke "v" using command down
						delay 0.2
						keystroke return

						-- wait until the Go To folder sheet disappears
						repeat while exists sheet 1
							delay 0.1
						end repeat

						delay 0.5

						-- Hit enter to confirm the Save sheet
						keystroke return
					end tell

					delay 0.5

					-- If a document existing prompt appears, click replace
					if exists sheet 1 of sheet 1 of window 1 then
						try
							click button "Replace" of sheet 1 of sheet 1 of window 1
						end try
					end if
				end tell
			end tell

			delay 1

			tell application "TextEdit"
				close document 1 saving no
			end tell
		end if
	end repeat

	tell application "TextEdit" to quit
	display dialog "Batch recursion and conversion to PDF complete!"
end run

on getFileNames(sourceFolder)
	set sourcePath to POSIX path of sourceFolder
	-- We use `do shell script` to perform an instant, deeply recursive search
	-- on the folder for all .doc files. It is thousands of times faster
	-- and much more reliable than native System Events recursion
	set cmd to "find " & quoted form of sourcePath & " -type f -iname \"*.doc\""
	try
		set findResult to do shell script cmd
		return paragraphs of findResult
	on error
		return {}
	end try
end getFileNames
