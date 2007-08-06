#!/usr/bin/env python
# encoding: utf-8

# This is a rewrite of latexErrWarn.py
# Goals:
#   1.  Modularize the processing of a latex run to better capture and parse errors
#   2.  replace latexmk
#   3.  provide a nice pushbutton interface for manually running latex,bibtex,mkindex, and viewing
#   
# Overview:
#    Each tex command has its own class that parses the output from that program.  Each of these classes
#    extends the TexParser class which provides default methods:
#       parseStream
#       error
#       warning
#       info
#   The parseStream method reads each line from the input stream matches against a set of regular
#   expressions defined in the patterns dictionary.  If one of these patterns matches then the 
#   corresponding method is called.  This method is also stored in the dictionary.  Pattern matching
#   callback methods must each take the match object as well as the current line as a parameter.
#
#   Progress:
#       7/17/07  -- Brad Miller
#       Implemented  TexParse, BibTexParser, and LaTexParser classes
#       see the TODO's sprinkled in the code below
#       7/24/07  -- Brad Miller
#       Spiffy new configuration window added
#       pushbutton interface at the end of the latex output is added
#       the confusing mass of code that was Typeset & View has been replaced by this one
#
#   Future:
# 
#       think about replacing latexmk.pl with a simpler python version.  If only rubber worked reliably..
#

import sys
import re
from os.path import basename
import os
import tmprefs
from urllib import quote
from struct import *
from texparser import *

# 

def run_bibtex(bibfile=None,verbose=False,texfile=None):
    """Determine Targets and run bibtex"""
    # find all the aux files.
    fatal,err,warn = 0,0,0
    if texfile:
        basename = texfile[:texfile.find('.tex')]
    if bibfile == None:
        auxfiles = [f for f in os.listdir('.') if re.search('.aux$',f) > 0]
        auxfiles = [f for f in auxfiles if re.match(r'('+ basename +r'\.aux|bu\d+\.aux)',f)]
    else:
        auxfiles = [bibfile]
    for bib in auxfiles:
        print '<h4>Processing: %s </h4>' % bib
        texin,tex = os.popen4('bibtex'+" "+shell_quote(bib))
        bp = BibTexParser(tex,verbose)
        f,e,w = bp.parseStream()
        fatal+=f
        err+=e
        warn+=w
        stat = tex.close()
    return stat,fatal,err,warn
        
def run_latex(ltxcmd,texfile,verbose=False):
    """Run the flavor of latex specified by ltxcmd on texfile"""
    global numRuns
    texin,tex = os.popen4(ltxcmd+" "+shell_quote(texfile))    
    lp = LaTexParser(tex,verbose)
    f,e,w = lp.parseStream()
    stat = tex.close()
    numRuns += 1
    return stat,f,e,w

def run_makeindex(fileName,idxfile=None):
    """Run the makeindex command"""
    idxFile = fileName.replace('.tex','.idx')
    texin,tex = os.popen4('makeindex ' + idxFile)
    ip = TexParser(tex,True)
    f,e,w = ip.parseStream()
    stat = tex.close()
    return stat,f,e,w

def findViewerPath(viewer,pdfFile,fileName):
    """Use the find_app command to ensure that the viewer is installed in the system
       For apps that support pdfsync search in pdf set up the command to go to the part of
       the page in the document the user was writing."""
    vp = os.popen('find_app ' + viewer + '.app').read()
    syncPath = None
    if viewer == 'Skim' and vp:
        syncPath = vp + '/Contents/Resources/displayline ' + os.getenv('TM_LINE_NUMBER') + ' ' + pdfFile + ' ' + os.getenv('TM_FILEPATH')
    elif viewer == 'TeXniscope' and vp:
        syncPath = vp + '/Contents/Resources/forward-search.sh ' + os.getenv('TM_LINE_NUMBER') + ' ' + os.getenv('TM_FILEPATH') + ' ' + pdfFile
    elif viewer == 'PDFView' and vp:
        syncPath = '/Contents/MacOS/gotoline.sh ' + os.getenv('TM_LINE_NUMBER') + ' ' + pdfFile
    return vp, syncPath

def run_viewer(viewer,fileName,filePath,force,usePdfSync=True):
    """If the viewer is textmate, then setup the proper urls and/or redirects to show the
       pdf file in the html output window.
       If the viewer is an external viewer then ensure that it is installed and display the pdf"""
    stat = 0
    if viewer != 'TextMate':
        pdfFile = shell_quote(fileName[:fileName.rfind('.tex')]+'.pdf')
        cmdPath,syncPath = findViewerPath(viewer,pdfFile,fileName)
        if cmdPath:
            viewCmd = '/usr/bin/open -a ' + viewer + '.app ' + pdfFile
            stat = os.system(viewCmd)
        else:
            print '<strong class="error">', viewer, ' does not appear to be installed on your system.</strong>'
        if syncPath and usePdfSync:
            os.system(syncPath)
        elif not syncPath and usePdfSync:
            print 'pdfsync is not supported for this viewer'
    else:
        pdfFile = fileName.replace('.tex','.pdf')
        tmHref = '<p><a href="tm-file://'+quote(filePath+'/'+pdfFile)+'">Click Here to View</a></p>'
        if (numErrs < 1 and numWarns < 1) or (numErrs < 1 and numWarns > 0 and not force):
            print '<script type="text/javascript">'
            print 'window.location="tm-file://'+quote(filePath+'/'+pdfFile)+'"'
            print '</script>'
    return stat

def determine_ts_directory(tsDirectives):
    """Determine the proper directory to use for typesetting the current document"""
    master = os.getenv('TM_LATEX_MASTER')
    texfile = os.getenv('TM_FILEPATH')
    startDir = os.path.dirname(texfile)

    if 'root' in tsDirectives:
        masterPath = os.path.dirname(os.path.normpath(tsDirectives['root']))
        return masterPath
    if master:
        masterPath = os.path.dirname(master)
        if masterPath == '' or masterPath[0] != '/':
            masterPath = os.path.normpath(startDir+'/'+masterPath)
    else:
        masterPath = startDir

    return masterPath

def findTexPackages(fileName):
    """Find all packages included by the master file.
       or any file included from the master.  We should not have to go
       more than one level deep for preamble stuff.
    """
    try:
        texString = open(fileName).read()
    except:
        print '<p class="error">Error: Could not open %s to check for packages</p>' % fileName
        print '<p class="error">This is most likely a problem with TM_LATEX_MASTER</p>'
        sys.exit(1)
    incFiles = [x[1] for x in re.findall(r'(\\input|\\include)\{([\w /\.\-]+)\}',texString)]
    myList = [x[1] for x in re.findall(r'\\usepackage(\[[\w, \-]+\])?\{([\w\-]+)\}',texString)]
    for ifile in incFiles:
        if ifile.find('.tex') < 0:
            ifile += '.tex'
        try:
            myList += [x[1] for x in re.findall(r'\\usepackage(\[[\w, \-]+\])?\{([\w\-]+)\}',open(ifile).read()) ]
        except:
            print 'Error: Could not open %s to check for packages' % ifile
            sys.exit(1)            
    return myList

def find_TEX_directives():
    """build a dictionary of %!TEX directives
       the main ones we are concerned with are
       root : which specifies a root file to run tex on for this subsidiary
       TS-program : which tells us which latex program to run
       TS-options : options to pass to TS-program
       encoding  :  file encoding
       """
    texfile = os.getenv('TM_FILEPATH')
    startDir = os.path.dirname(texfile)
    done = False    
    tsDirectives = {}
    while not done:
        f = open(texfile)
        foundNewRoot = False
        for i in range(20):
            line = f.readline()
            m =  re.match(r'^%!TEX\s+([\w-]+)\s?=\s?(.*)',line)
            if m:
                if m.group(1) == 'root':
                    foundNewRoot = True
                    if m.group(2)[0] == '/':
                        texfile = m.group(2).rstrip()
                    else:                           # new root is relative or in same directory
                        texfile = startDir + '/' + m.group(2).rstrip()
                    tsDirectives['root'] = texfile
                else:
                    tsDirectives[m.group(1)] = m.group(2).rstrip()
        f.close()
        if foundNewRoot == False:
            done = True

    return tsDirectives

def findFileToTypeset(tsDirectives):
    """determine which file to typeset.  Using the following rules:
       + %!TEX root directive
       + using the TM_LATEX_MASTER environment variable
       + Using TM_FILEPATH
       Once the file is decided return the name of the file and the normalized absolute path to the
       file as a tuple.
    """
    if  'root' in tsDirectives:
        f = tsDirectives['root']
    elif os.getenv('TM_LATEX_MASTER'):
        f = os.getenv('TM_LATEX_MASTER')
    else:
        f = os.getenv('TM_FILEPATH')
    master = os.path.basename(f)

    return master,determine_ts_directory(tsDirectives)

def constructEngineOptions(tsDirectives,tmPrefs):
    """Construct a string of command line options to pass to the typesetting engine
    Options can come from:
    +  %!TEX TS-options directive in the file
    + Preferences
    In any case nonstopmode is set as is file-line-error-style.
    """
    opts = "-interaction=nonstopmode -file-line-error-style"
    if 'TS-options' in tsDirectives:
        opts += " " + tsDirectives['TS-options']
    else:
        opts += " " + tmPrefs['latexEngineOptions']
    return opts

def usesOnePackage(testPack, allPackages):
    for p in testPack:
        if p in allPackages:
            return True
    return False

def constructEngineCommand(tsDirectives,tmPrefs,packages):
    """This function decides which engine to run using 
       + %!TEX directives from the tex file
       + Preferences
       + or by detecting certain packages
       The default is pdflatex.  But it may be modified
       to be one of
          latex
          xelatex
          texexec  -- although I'm not sure how compatible context is with any of this
    """
    engine = "pdflatex"

    latexIndicators = ['pstricks' , 'xyling' , 'pst-asr' , 'OTtablx' , 'epsfig' ]
    xelatexIndicators = ['xunicode', 'fontspec']

    if 'TS-program' in tsDirectives:
        engine = tsDirectives['TS-program']
    elif usesOnePackage(latexIndicators,packages):
        engine = 'latex'
    elif usesOnePackage(xelatexIndicators,packages):
        engine = 'xelatex'
    else:
        engine = tmPrefs['latexEngine']
    stat = os.system('/usr/bin/type '+engine+" > /dev/null")
    if stat != 0:
        print 'Error: %s is not found' % engine
        sys.exit(1)
    return engine

###############################################################
#                                                             #
#                 Start of main program...                    #
#                                                             #
###############################################################

if __name__ == '__main__':
    verbose = False
    numRuns = 0
    stat = 0
    texStatus = None
    numErrs = 0
    numWarns = 0
    firstRun = False

#
# Parse command line parameters...
#
    if len(sys.argv) > 2:
        firstRun = True         ## A little hack to make the buttons work nicer.
    if len(sys.argv) > 1:
        texCommand = sys.argv[1]
    else:
        sys.stderr.write("Usage: "+sys.argv[0]+" tex-command firstRun\n")
        sys.exit(255)

#
# Get preferences from TextMate or local directives
#
    tmPrefs = tmprefs.Preferences()
    tsDirs = find_TEX_directives()
    os.chdir(determine_ts_directory(tsDirs))
    
#
# Set up some configuration variables
#
    if tmPrefs['latexVerbose'] == 1:
        verbose = True

    useLatexMk = tmPrefs['latexUselatexmk']
    if texCommand == 'latex' and useLatexMk:
        texCommand = 'latexmk'
    
    if texCommand == 'latex' and tmPrefs['latexEngine'] == 'builtin':
        texCommand = 'builtin'

    fileName,filePath = findFileToTypeset(tsDirs);

    ltxPackages = findTexPackages(fileName)
        
    viewer = tmPrefs['latexViewer']
    engine = constructEngineCommand(tsDirs,tmPrefs,ltxPackages)

    # Make sure that the bundle_support/tex directory is added
    #pcmd = os.popen("kpsewhich -progname %s --expand-var '$TEXINPUTS':%s/tex//" % (engine,bundle_support))
    #texinputs = pcmd.read()
    #using the output of kpsewhich fails to work properly.  The simpler method below works fine
    if os.getenv('TEXINPUTS'):
        texinputs = os.getenv('TEXINPUTS') + ':'
    else:
        texinputs = ".::"
    texinputs += "%s/tex//" % os.getenv('TM_BUNDLE_SUPPORT')
    os.putenv('TEXINPUTS',texinputs)

#
# print out header information to begin the run
#
    if not firstRun:
        print '<hr>'
    print '<h2>Running %s on %s</h2>' % (engine,fileName)
    print '<div id="commandOutput"><div id="preText">'

#
# Run the command passed on the command line or modified by preferences
#
    if texCommand == 'latexmk':
        texCommand = 'latexmk.pl -f -r ' + shell_quote(os.getenv('TM_BUNDLE_SUPPORT'))+'/latexmkrc'
        print texCommand
        texin,tex = os.popen4(texCommand+" "+shell_quote(fileName))
        commandParser = ParseLatexMk(tex,verbose)
        isFatal,numErrs,numWarns = commandParser.parseStream()
        texStatus = tex.close()
        if tmPrefs['latexAutoView'] and numErrs < 1:
            stat = run_viewer(viewer,fileName,filePath,tmPrefs['latexKeepLogWin'],'pdfsync' in ltxPackages)

    elif texCommand == 'bibtex':
        texStatus, isFatal, numErrs, numWarns = run_bibtex(texfile=fileName)
        
    elif texCommand == 'index':
        texStatus, isFatal, numErrs, numWarns = run_makeindex(fileName)
        
    elif texCommand == 'builtin':
        # the latex, bibtex, index, latex, latex sequence should cover 80% of the cases that latexmk does
        texCommand =  engine + " " + constructEngineOptions(tsDirs,tmPrefs)
        texStatus,isFatal,numErrs,numWarns = run_latex(texCommand,fileName,verbose)
        texStatus, isFatal, numErrs, numWarns = run_bibtex(texfile=fileName)
        if os.path.exists(fileName.replace('.tex','.idx')):
            texStatus, isFatal, numErrs, numWarns = run_makeindex(fileName)
        texStatus,isFatal,numErrs,numWarns = run_latex(texCommand,fileName,verbose)
        texStatus,isFatal,numErrs,numWarns = run_latex(texCommand,fileName,verbose)
        
    elif texCommand =='latex':
        texCommand = engine + " " + constructEngineOptions(tsDirs,tmPrefs)
        texStatus,isFatal,numErrs,numWarns = run_latex(texCommand,fileName,verbose)
        if engine == 'latex':
            psFile = fileName.replace('.tex','.ps')
            os.system('dvips ' + fileName.replace('.tex','.dvi') + ' -o ' + psFile)
            os.system('ps2pdf ' + psFile)
        if tmPrefs['latexAutoView'] and numErrs < 1:
            stat = run_viewer(viewer,fileName,filePath,tmPrefs['latexKeepLogWin'],'pdfsync' in ltxPackages)
        
    elif texCommand == 'view':
        stat = run_viewer(viewer,fileName,filePath,tmPrefs['latexKeepLogWin'],'pdfsync' in ltxPackages)
#    
# Check status of running the viewer
#
    if stat != 0:
        print '<p class="error"><strong>error number %d opening viewer</strong></p>' % stat

#
# Check the status of any runs...
#
    eCode = 0
    if texStatus != None or numWarns > 0 or numErrs > 0:
        print "<p class='info'>Found " + str(numErrs) + " errors, and " + str(numWarns) + " warnings in " + str(numRuns) + " runs</p>"
        if texStatus != None:
            signal = (texStatus & 255)
            returnCode = texStatus >> 8
            if signal != 0:
                print "<p class='error'>TeX killed by signal %s</p>" % str(signal) 
            else:
                print "<p class='error'>TeX exited with error code %s</p> " % str(returnCode)
#
# Decide what to do with the Latex & View log window   
#
    if not tmPrefs['latexKeepLogWin']:
        if numErrs == 0 and numWarns == 0 and viewer != 'TextMate':
            eCode = 200
        else:
            eCode = 0
    else:
        eCode = 0

    print '</div></div>'  # closes <pre> and <div id="commandOutput"> 

#
# Output buttons at the bottom of the window
#
    if firstRun:
        # only need to include the javascript library once
        js = os.getenv('TM_BUNDLE_SUPPORT') + '/bin/texlib.js'
        js = quote(js)
        print """
         <script src="file://%s"    type="text/javascript" charset="utf-8"></script>
         """ % js

        print '<div id="texActions">'
        print '<input type="button" value="Re-Run %s" onclick="runLatex(); return false" />' % engine
        print '<input type="button" value="Run BibTeX" onclick="runBibtex(); return false" />'
        print '<input type="button" value="Run Makeindex" onclick="runMakeIndex(); return false" />'
        if viewer == 'TextMate':
            pdfFile = fileName.replace('.tex','.pdf')
            print """<input type="button" value="view in TextMate" onclick="window.location='""" + 'tm-file://' + quote(filePath+'/'+pdfFile) +"""'"/>"""
        else:
            print '<input type="button" value="View in %s" onclick="runView(); return false" />' % viewer
        print '<input type="button" value="Preferences…" onclick="runConfig(); return false" />'
        print '<p>'
        print '<input type="checkbox" id="hv_warn" name="fmtWarnings" onclick="makeFmtWarnVisible(); return false" />'
        print '<label for="hv_warn">Show hbox,vbox Warnings </label>'            
        print '</div>'

    sys.exit(eCode)