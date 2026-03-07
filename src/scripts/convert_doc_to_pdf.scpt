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
		set posixTarget to aFile as text

		-- Case-insensitive check for .doc extension
		if (posixTarget as lowercase) ends with ".doc" then
			set newPath to (text 1 thru -5 of posixTarget) & ".pdf"

			-- Generate HFS path and get parent directory for the "Go to Folder" sheet
			set fileAlias to POSIX file posixTarget as alias
			set parentPath to getParentPath(posixTarget)
			set pdfName to getFileName(newPath)

			tell application "TextEdit"
				set targetDoc to open fileAlias
			end tell

			tell application "System Events"
				tell process "TextEdit"
					set frontmost to true
					try
						-- Usually the menu item is "Export as PDF…" with an ellipsis (Option-semicolon)
						try
							click menu item "Export as PDF…" of menu "File" of menu bar 1
						on error
							-- Fallback to three-dot version
							click menu item "Export as PDF..." of menu "File" of menu bar 1
						end try

						-- Wait for save sheet with timeout
						set waitCount to 0
						repeat until (exists sheet 1 of window 1) or (waitCount > 50)
							delay 0.1
							set waitCount to waitCount + 1
						end repeat
						if waitCount > 50 then error "Timeout waiting for Export sheet"

						tell sheet 1 of window 1
							-- change directory by invoking "Go to Folder"
							keystroke "g" using {command down, shift down}

							-- wait for the Go To folder sheet
							set waitCount to 0
							repeat until (exists sheet 1) or (waitCount > 30)
								delay 0.1
								set waitCount to waitCount + 1
							end repeat
							if waitCount > 30 then error "Timeout waiting for Go To Folder sheet"

							delay 0.2
							set oldClipboard to the clipboard
							set the clipboard to parentPath
							keystroke "v" using command down
							delay 0.2
							keystroke return

							-- wait until the Go To folder sheet disappears
							set waitCount to 0
							repeat while (exists sheet 1) and (waitCount < 50)
								delay 0.1
								set waitCount to waitCount + 1
							end repeat

							delay 0.2
							-- Set the PDF filename
							set the clipboard to pdfName
							keystroke "v" using command down
							set the clipboard to oldClipboard
							delay 0.2

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
					on error errMsg
						display dialog "Unable to control TextEdit via System Events." & return & return & ¬
							"Please enable “TextEdit” and “System Events” in:" & return & ¬
							"  • System Settings > Privacy & Security > Accessibility" & return & ¬
							"  • System Settings > Privacy & Security > Automation" & return & return & ¬
							"Error: " & errMsg buttons {"OK"} default button 1
						error number -128
					end try
				end tell
			end tell

			delay 1

			tell application "TextEdit"
				close targetDoc saving no
			end tell
		end if
	end repeat

	tell application "TextEdit" to quit
	display dialog "Batch recursion and conversion to PDF complete!"
end run

on getFileNames(sourceFolder)
	set sourcePath to POSIX path of sourceFolder
	set cmd to "find " & quoted form of sourcePath & " -type f -iname \"*.doc\""
	try
		set findResult to do shell script cmd
		return paragraphs of findResult
	on error
		return {}
	end try
end getFileNames

on getParentPath(posixPath)
	set cmd to "dirname " & quoted form of posixPath
	return (do shell script cmd) & "/"
end getParentPath

on getFileName(posixPath)
	set cmd to "basename " & quoted form of posixPath
	return do shell script cmd
end getFileName
